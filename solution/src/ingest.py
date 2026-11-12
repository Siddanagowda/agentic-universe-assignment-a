import csv
import hashlib
import json
import sqlite3
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
    for field in fields:
        for name in [field["name"], *field.get("aliases", [])]:
            aliases[normalize_header(name)] = field

    counts = {
        "rows": 0,
        "rejected": 0,
        "duplicates": 0,
        "warnings": 0,
        "skipped": False,
    }
    batch_id = path.stem

    with path.open(newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)
        mapped = {}
        for column in reader.fieldnames or []:
            field = aliases.get(normalize_header(column))
            if field:
                mapped[column] = field["name"]

        data_row_number = 0
        for row in reader:
            if not any(str(value or "").strip() for value in row.values()):
                continue

            data_row_number += 1
            counts["rows"] += 1
            raw_values = {}
            for column, raw in row.items():
                field_name = mapped.get(column)
                if field_name:
                    raw_values[field_name] = raw

            values = {field["name"]: None for field in fields}
            warning = 0
            reason = None

            # Validate in schema order so the first rejection is deterministic.
            for field in fields:
                name = field["name"]
                raw = raw_values.get(name)
                try:
                    values[name] = normalize_value(field, raw)
                except ValueError:
                    if field["type"] == "phone" and str(raw or "").strip():
                        reason = "invalid_phone"
                        break
                    if field.get("required"):
                        reason = f"missing_required:{name}"
                        break
                    values[name] = None
                    warning += 1

                if field.get("required") and not values[name]:
                    reason = f"missing_required:{name}"
                    break

            if reason:
                counts["rejected"] += 1
                conn.execute(
                    """INSERT OR IGNORE INTO rejections
                       (workflow_id,batch_id,row_number,reason)
                       VALUES(?,?,?,?)""",
                    (
                        schema["workflow_id"],
                        batch_id,
                        data_row_number,
                        reason,
                    ),
                )
                continue

            phone = values["phone"]
            digest_phone = phone_digest(phone)
            ref_field = next(
                field["name"] for field in fields if field.get("reference")
            )
            external_ref = values[ref_field]
            existing = conn.execute(
                """SELECT id,attributes_json FROM leads
                   WHERE workflow_id=? AND phone_hash=?""",
                (schema["workflow_id"], digest_phone),
            ).fetchone()

            pii_fields = {
                field["name"] for field in fields if field.get("pii")
            }
            attributes = {
                key: value
                for key, value in values.items()
                if key not in pii_fields and key != "phone"
            }

            if existing:
                counts["duplicates"] += 1
                merged = json.loads(existing["attributes_json"])
                merged.update(
                    {key: value for key, value in attributes.items() if value is not None}
                )
                # Defaults apply after merging, only where the merged value is null.
                for field in fields:
                    name = field["name"]
                    if merged.get(name) is None and "default" in field:
                        merged[name] = field["default"]

                conn.execute(
                    """UPDATE leads
                       SET customer_name_cipher=COALESCE(?,customer_name_cipher),
                           external_ref=COALESCE(?,external_ref),
                           attributes_json=?
                       WHERE id=?""",
                    (
                        encrypt(values.get("customer_name")),
                        external_ref,
                        json.dumps(merged, ensure_ascii=False),
                        existing["id"],
                    ),
                )
            else:
                for field in fields:
                    name = field["name"]
                    if values.get(name) is None and "default" in field:
                        values[name] = field["default"]
                attributes = {
                    key: value
                    for key, value in values.items()
                    if key not in pii_fields and key != "phone"
                }
                conn.execute(
                    """INSERT INTO leads
                       (workflow_id,phone_hash,phone_cipher,customer_name_cipher,
                        external_ref,batch_id,attributes_json)
                       VALUES(?,?,?,?,?,?,?)""",
                    (
                        schema["workflow_id"],
                        digest_phone,
                        encrypt(phone),
                        encrypt(values.get("customer_name")),
                        external_ref,
                        batch_id,
                        json.dumps(attributes, ensure_ascii=False),
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

    counts = {
        "total": 0,
        "malformed": 0,
        "duplicates": 0,
        "skipped": False,
    }

    with path.open(encoding="utf-8") as source:
        for line in source:
            if not line.strip():
                continue
            counts["total"] += 1

            try:
                event = json.loads(line)
                if not isinstance(event, dict):
                    raise ValueError("event must be a JSON object")

                event_id = event.get("event_id")
                if not event_id:
                    raise ValueError("missing event_id")

                event_type = event.get("event_type")
                workflow = event.get("workflow_id")
                occurred_at = parse_timestamp(event.get("occurred_at"))
                payload = event.get("payload") or {}
                if not isinstance(payload, dict):
                    raise ValueError("payload must be a JSON object")

                phone_hash = None
                if event.get("phone"):
                    try:
                        phone_hash = phone_digest(normalize_phone(event["phone"]))
                    except ValueError:
                        phone_hash = None

                is_disposition = event_type in (
                    "disposition.set",
                    "disposition.override",
                )
                code = payload.get("disposition_code") if is_disposition else None
                known = (
                    code in dispositions.get(workflow, set())
                    if is_disposition
                    else True
                )

                # Keep the event record, but never persist a plaintext phone number.
                stored_event = dict(event)
                if stored_event.get("phone"):
                    stored_event["phone"] = encrypt(str(stored_event["phone"]))

                try:
                    conn.execute(
                        """INSERT INTO events
                           (event_id,workflow_id,event_type,call_id,occurred_at,
                            phone_hash,payload_json,raw_json,disposition_known,ingested_drop)
                           VALUES(?,?,?,?,?,?,?,?,?,?)""",
                        (
                            event_id,
                            workflow,
                            event_type,
                            event.get("call_id"),
                            occurred_at,
                            phone_hash,
                            json.dumps(payload, ensure_ascii=False),
                            json.dumps(stored_event, ensure_ascii=False),
                            int(known),
                            drop_name,
                        ),
                    )
                except sqlite3.IntegrityError as exc:
                    if "events.event_id" in str(exc):
                        counts["duplicates"] += 1
                        continue
                    raise

            except (
                json.JSONDecodeError,
                ValueError,
                TypeError,
                AttributeError,
                KeyError,
                sqlite3.IntegrityError,
            ):
                counts["malformed"] += 1

    conn.execute(
        "INSERT INTO processed_files(path,content_sha256) VALUES(?,?)",
        (str(path), digest),
    )
    return counts


def reconcile_events(conn):
    # Resolve events with a phone first, including events from earlier drops.
    conn.execute(
        """UPDATE events SET lead_id=(
               SELECT l.id FROM leads l
               WHERE l.workflow_id=events.workflow_id
                 AND l.phone_hash=events.phone_hash
           )
           WHERE phone_hash IS NOT NULL"""
    )

    # Overrides have no phone. Resolve them through another event from the same call.
    conn.execute(
        """UPDATE events SET lead_id=(
               SELECT e2.lead_id FROM events e2
               WHERE e2.workflow_id=events.workflow_id
                 AND e2.call_id=events.call_id
                 AND e2.lead_id IS NOT NULL
               ORDER BY CASE WHEN e2.event_type='call.initiated' THEN 0 ELSE 1 END,
                        e2.id
               LIMIT 1
           )
           WHERE event_type='disposition.override'
             AND lead_id IS NULL
             AND call_id IS NOT NULL"""
    )
