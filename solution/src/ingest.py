import csv, hashlib, json
from pathlib import Path
from .normalizers import (
    normalize_header,
    normalize_value,
    parse_timestamp,
    normalize_phone,
)
from .security import phone_digest, encrypt


def _file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _already_processed(conn, path, digest):
    row = conn.execute(
        "SELECT content_sha256 FROM processed_files WHERE path=?", (str(path),)
    ).fetchone()
    if row and row["content_sha256"] == digest:
        return True
    if row and row["content_sha256"] != digest:
        raise ValueError(f"Previously ingested file changed: {path}")
    return False


def ingest_lead_file(conn, path, schema, drop_name):
    path = Path(path)
    digest = _file_hash(path)
    if _already_processed(conn, path, digest):
        return {
            "rows": 0,
            "rejected": 0,
            "duplicates": 0,
            "warnings": 0,
            "skipped": True,
        }
    fields = schema["fields"]
    aliases = {}
    for f in fields:
        for name in [f["name"], *f.get("aliases", [])]:
            aliases[normalize_header(name)] = f
    counts = {
        "rows": 0,
        "rejected": 0,
        "duplicates": 0,
        "warnings": 0,
        "skipped": False,
    }
    batch_id = path.stem
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        mapped = {}
        for col in reader.fieldnames or []:
            field = aliases.get(normalize_header(col))
            if field:
                mapped[col] = field
        for row_num, row in enumerate(reader, 1):
            if not any(str(v or "").strip() for v in row.values()):
                continue
            counts["rows"] += 1
            values = {f["name"]: None for f in fields}
            warning = 0
            reason = None
            for col, raw in row.items():
                field = mapped.get(col)
                if not field:
                    continue
                try:
                    values[field["name"]] = normalize_value(field, raw)
                except ValueError as exc:
                    if field["type"] == "phone" and str(raw or "").strip():
                        reason = "invalid_phone"
                        break
                    if field.get("required") and not str(raw or "").strip():
                        reason = f"missing_required:{field['name']}"
                        break
                    values[field["name"]] = None
                    warning += 1
            if not reason:
                for field in fields:
                    if field.get("required") and not values.get(field["name"]):
                        reason = f"missing_required:{field['name']}"
                        break
            if reason:
                counts["rejected"] += 1
                conn.execute(
                    "INSERT OR IGNORE INTO rejections(workflow_id,batch_id,row_number,reason) VALUES(?,?,?,?)",
                    (schema["workflow_id"], batch_id, row_num, reason),
                )
                continue
            counts["warnings"] += warning
            phone = values["phone"]
            digest_phone = phone_digest(phone)
            ref_field = next(f["name"] for f in fields if f.get("reference"))
            external_ref = values[ref_field]
            existing = conn.execute(
                "SELECT id,attributes_json FROM leads WHERE workflow_id=? AND phone_hash=?",
                (schema["workflow_id"], digest_phone),
            ).fetchone()
            # PII values are encrypted; non-PII attributes remain queryable.
            pii = {f["name"] for f in fields if f.get("pii")}
            attrs = {k: v for k, v in values.items() if k not in pii and k != "phone"}
            if existing:
                counts["duplicates"] += 1
                old = json.loads(existing["attributes_json"])
                old.update({k: v for k, v in attrs.items() if v is not None})
                conn.execute(
                    "UPDATE leads SET customer_name_cipher=COALESCE(?,customer_name_cipher), external_ref=COALESCE(?,external_ref), attributes_json=? WHERE id=?",
                    (
                        encrypt(values.get("customer_name")),
                        external_ref,
                        json.dumps(old),
                        existing["id"],
                    ),
                )
            else:
                for field in fields:
                    if values.get(field["name"]) is None and "default" in field:
                        values[field["name"]] = field["default"]
                attrs = {
                    k: v for k, v in values.items() if k not in pii and k != "phone"
                }
                conn.execute(
                    """INSERT INTO leads(workflow_id,phone_hash,phone_cipher,customer_name_cipher,external_ref,batch_id,attributes_json)
                                VALUES(?,?,?,?,?,?,?)""",
                    (
                        schema["workflow_id"],
                        digest_phone,
                        encrypt(phone),
                        encrypt(values.get("customer_name")),
                        external_ref,
                        batch_id,
                        json.dumps(attrs, ensure_ascii=False),
                    ),
                )
    conn.execute(
        "INSERT INTO processed_files(path,content_sha256) VALUES(?,?)",
        (str(path), digest),
    )
    return counts


def ingest_event_file(conn, path, dispositions, drop_name):
    path = Path(path)
    digest = _file_hash(path)
    if _already_processed(conn, path, digest):
        return {"total": 0, "malformed": 0, "duplicates": 0, "skipped": True}
    c = {"total": 0, "malformed": 0, "duplicates": 0, "skipped": False}
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            c["total"] += 1
            try:
                obj = json.loads(line)
                event_id = obj.get("event_id")
                if not event_id:
                    raise ValueError("missing event_id")
                etype = obj.get("event_type")
                workflow = obj.get("workflow_id")
                occurred = parse_timestamp(obj.get("occurred_at"))
                payload = obj.get("payload") or {}
                phone_hash = None
                if obj.get("phone"):
                    try:
                        phone_hash = phone_digest(normalize_phone(obj["phone"]))
                    except ValueError:
                        phone_hash = None
                code = (
                    payload.get("disposition_code")
                    if etype in ("disposition.set", "disposition.override")
                    else None
                )
                known = True
                if code:
                    known = code in dispositions.get(workflow, set())
                try:
                    conn.execute(
                        """INSERT INTO events(event_id,workflow_id,event_type,call_id,occurred_at,phone_hash,payload_json,raw_json,disposition_known,ingested_drop)
                                    VALUES(?,?,?,?,?,?,?,?,?,?)""",
                        (
                            event_id,
                            workflow,
                            etype,
                            obj.get("call_id"),
                            occurred,
                            phone_hash,
                            json.dumps(payload),
                            json.dumps(obj, ensure_ascii=False),
                            int(known),
                            drop_name,
                        ),
                    )
                except Exception as exc:
                    if "UNIQUE constraint failed: events.event_id" in str(exc):
                        c["duplicates"] += 1
                        continue
                    raise
            except (
                json.JSONDecodeError,
                ValueError,
                TypeError,
                AttributeError,
                KeyError,
            ):
                c["malformed"] += 1
    conn.execute(
        "INSERT INTO processed_files(path,content_sha256) VALUES(?,?)",
        (str(path), digest),
    )
    return c


def reconcile_events(conn):
    # First resolve phone-linked events; then resolve phone-less overrides via call_id.
    conn.execute("""UPDATE events SET lead_id=(
        SELECT l.id FROM leads l WHERE l.workflow_id=events.workflow_id AND l.phone_hash=events.phone_hash
    ) WHERE phone_hash IS NOT NULL""")
    conn.execute(
        """UPDATE events SET lead_id=(
        SELECT e2.lead_id FROM events e2 WHERE e2.call_id=events.call_id AND e2.lead_id IS NOT NULL
        ORDER BY CASE WHEN e2.event_type='call.initiated' THEN 0 ELSE 1 END, e2.id LIMIT 1
    ) WHERE event_type='disposition.override' AND lead_id IS NULL AND call_id IS NOT NULL"""
    )
