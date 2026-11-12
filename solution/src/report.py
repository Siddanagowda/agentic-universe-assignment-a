import csv, json
from pathlib import Path
from collections import defaultdict
from datetime import datetime
from .normalizers import ist_date, ist_timestamp
from .security import decrypt


def load_dispositions(path):
    result = defaultdict(dict)
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            result[row["workflow_id"]][row["code"]] = {
                "terminal": row["is_terminal"].lower() == "true",
                "success": row["is_success"].lower() == "true",
            }
    return result


def generate_reports(conn, out_dir, dispositions, quality):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    leads = conn.execute(
        "SELECT * FROM leads ORDER BY workflow_id,external_ref"
    ).fetchall()
    events = conn.execute(
        "SELECT * FROM events WHERE lead_id IS NOT NULL ORDER BY occurred_at,id"
    ).fetchall()
    by_lead = defaultdict(list)
    by_call = defaultdict(list)
    for e in events:
        by_lead[e["lead_id"]].append(e)
        if e["call_id"]:
            by_call[(e["lead_id"], e["call_id"])].append(e)

    def disposition_for(call_events):
        overrides = [
            e
            for e in call_events
            if e["event_type"] == "disposition.override" and e["disposition_known"]
        ]
        sets = [
            e
            for e in call_events
            if e["event_type"] == "disposition.set" and e["disposition_known"]
        ]
        chosen = max(overrides or sets, key=lambda e: e["occurred_at"], default=None)
        return (
            json.loads(chosen["payload_json"]).get("disposition_code")
            if chosen
            else None
        )

    call_info = {}
    for (lid, cid), evs in by_call.items():
        initiated = [e for e in evs if e["event_type"] == "call.initiated"]
        if not initiated:
            continue
        start = min(initiated, key=lambda e: e["occurred_at"])
        disp = disposition_for(evs)
        call_info.setdefault(lid, []).append(
            {
                "call_id": cid,
                "start": start["occurred_at"],
                "connected": any(e["event_type"] == "call.connected" for e in evs),
                "disposition": disp,
                "telephony_failed": any(
                    e["event_type"] == "call.telephony_failed" for e in evs
                ),
            }
        )
    for lid in call_info:
        call_info[lid].sort(key=lambda c: c["start"])
    # Batch summary
    batch = defaultdict(lambda: defaultdict(int))
    lead_rows = []
    daily = defaultdict(lambda: {"total": 0, "connected": 0, "success_leads": set()})
    for lead in leads:
        calls = call_info.get(lead["id"], [])
        eff = [c["disposition"] for c in calls if c["disposition"]]
        if not calls:
            bucket = "yet_to_reach_out"
        elif any(
            dispositions[lead["workflow_id"]].get(d, {}).get("terminal") for d in eff
        ):
            bucket = "completed"
        elif all(c["telephony_failed"] for c in calls):
            bucket = "in_progress_telephony_failed"
        else:
            bucket = "in_progress_dialed"
        batch[(lead["workflow_id"], lead["batch_id"])][bucket] += 1
        batch[(lead["workflow_id"], lead["batch_id"])]["total_leads"] += 1
        for c in calls:
            day = ist_date(c["start"])
            key = (lead["workflow_id"], day)
            daily[key]["total"] += 1
            daily[key]["connected"] += int(c["connected"])
            if c["disposition"] and dispositions[lead["workflow_id"]].get(
                c["disposition"], {}
            ).get("success"):
                daily[key]["success_leads"].add(lead["id"])
        current = next(
            (c["disposition"] for c in reversed(calls) if c["disposition"]), None
        )
        ever = any(
            dispositions[lead["workflow_id"]].get(d, {}).get("success") for d in eff
        )
        phone = decrypt(lead["phone_cipher"])
        last = ist_timestamp(calls[-1]["start"]) if calls else ""
        lead_rows.append(
            [
                lead["workflow_id"],
                lead["external_ref"],
                lead["batch_id"],
                "+91******" + phone[-4:],
                bucket,
                len(calls),
                sum(c["connected"] for c in calls),
                last,
                current or "",
                str(bool(ever)).lower(),
            ]
        )

    def write(name, header, rows):
        with (out / name).open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(header)
            w.writerows(rows)

    batch_header = [
        "workflow_id",
        "batch_id",
        "total_leads",
        "yet_to_reach_out",
        "in_progress_telephony_failed",
        "in_progress_dialed",
        "completed",
    ]
    batch_rows = []
    for (wf, bid), v in sorted(batch.items()):
        batch_rows.append(
            [
                wf,
                bid,
                v["total_leads"],
                v["yet_to_reach_out"],
                v["in_progress_telephony_failed"],
                v["in_progress_dialed"],
                v["completed"],
            ]
        )
    write("batch_summary.csv", batch_header, batch_rows)
    daily_rows = []
    for (wf, day), v in sorted(daily.items()):
        rate = v["connected"] / v["total"] if v["total"] else 0
        daily_rows.append(
            [
                wf,
                day,
                v["total"],
                v["connected"],
                f"{rate:.4f}",
                len(v["success_leads"]),
            ]
        )
    write(
        "daily_overview.csv",
        [
            "workflow_id",
            "date",
            "total_calls",
            "connected_calls",
            "connectivity_rate",
            "success_leads",
        ],
        daily_rows,
    )
    write(
        "lead_report.csv",
        [
            "workflow_id",
            "external_ref",
            "batch_id",
            "phone_masked",
            "bucket",
            "total_calls",
            "connected_calls",
            "last_call_at",
            "current_disposition",
            "ever_success",
        ],
        lead_rows,
    )
    rej = conn.execute(
        "SELECT workflow_id,batch_id,row_number,reason FROM rejections ORDER BY workflow_id,batch_id,row_number"
    ).fetchall()
    write(
        "rejections.csv",
        ["workflow_id", "batch_id", "row_number", "reason"],
        [list(r) for r in rej],
    )
    quality = dict(quality)
    quality["orphan_events"] = conn.execute(
        "SELECT COUNT(*) FROM events WHERE lead_id IS NULL"
    ).fetchone()[0]
    (out / "data_quality.json").write_text(
        json.dumps(quality, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
