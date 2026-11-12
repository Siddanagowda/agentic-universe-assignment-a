import argparse, json
from pathlib import Path
from .db import connect
from .ingest import ingest_lead_file, ingest_event_file, reconcile_events
from .report import load_dispositions, generate_reports
from .config import SCHEMA_DIR, DEFAULT_DB


def main():
    p = argparse.ArgumentParser(prog="au-pipeline")
    p.add_argument("--db", default=str(DEFAULT_DB))
    sub = p.add_subparsers(dest="command", required=True)
    ing = sub.add_parser("ingest")
    ing.add_argument("drop")
    rep = sub.add_parser("report")
    rep.add_argument("--out", default="reports")
    args = p.parse_args()
    conn = connect(args.db)
    disp = load_dispositions(SCHEMA_DIR / "dispositions.csv")
    if args.command == "ingest":
        root = Path(args.drop)
        quality = {
            "lead_rows_total": 0,
            "lead_rows_rejected": 0,
            "rejections_by_reason": {},
            "duplicate_lead_rows_merged": 0,
            "field_warnings": 0,
            "events_total": 0,
            "malformed_events": 0,
            "duplicate_events_dropped": 0,
            "unknown_disposition_events": 0,
        }
        for file in sorted(root.glob("leads/*/*.csv")):
            schema_path = SCHEMA_DIR / (file.parent.name + ".json")
            schema = json.loads(schema_path.read_text())
            c = ingest_lead_file(conn, file, schema, root.name)
            quality["lead_rows_total"] += c["rows"]
            quality["lead_rows_rejected"] += c["rejected"]
            quality["duplicate_lead_rows_merged"] += c["duplicates"]
            quality["field_warnings"] += c["warnings"]
        # Cumulative quality counters are persisted so each drop can be ingested separately.
        for file in sorted(root.glob("events/*.jsonl")):
            c = ingest_event_file(
                conn, file, {wf: set(x) for wf, x in disp.items()}, root.name
            )
            quality["events_total"] += c["total"]
            quality["malformed_events"] += c["malformed"]
            quality["duplicate_events_dropped"] += c["duplicates"]
        reconcile_events(conn)
        # Derive global quality metrics from persistent tables and file-ingestion totals.
        quality["lead_rows_rejected"] = conn.execute(
            "SELECT COUNT(*) FROM rejections"
        ).fetchone()[0]
        quality["rejections_by_reason"] = {}
        for r in conn.execute(
            "SELECT reason,COUNT(*) n FROM rejections GROUP BY reason ORDER BY reason"
        ):
            quality["rejections_by_reason"][r["reason"]] = r["n"]
        quality["duplicate_lead_rows_merged"] = max(
            quality["duplicate_lead_rows_merged"], 0
        )
        print(
            json.dumps(
                {
                    "drop": root.name,
                    "leads": quality["lead_rows_total"],
                    "events": quality["events_total"],
                    "reconciled": True,
                },
                indent=2,
            )
        )
        # Store per-drop counters for report generation.
        counter_names = [
            "lead_rows_total",
            "duplicate_lead_rows_merged",
            "field_warnings",
            "events_total",
            "malformed_events",
            "duplicate_events_dropped",
        ]
        for name in counter_names:
            conn.execute(
                "INSERT INTO counters(name,value) VALUES(?,?) ON CONFLICT(name) DO UPDATE SET value=value+excluded.value",
                (name, quality[name]),
            )
        conn.commit()
    elif args.command == "report":
        q = {r["name"]: r["value"] for r in conn.execute("SELECT * FROM counters")}
        quality = {
            "lead_rows_total": q.get("lead_rows_total", 0),
            "lead_rows_rejected": conn.execute(
                "SELECT COUNT(*) FROM rejections"
            ).fetchone()[0],
            "rejections_by_reason": {
                r["reason"]: r["n"]
                for r in conn.execute(
                    "SELECT reason,COUNT(*) n FROM rejections GROUP BY reason ORDER BY reason"
                )
            },
            "duplicate_lead_rows_merged": q.get("duplicate_lead_rows_merged", 0),
            "field_warnings": q.get("field_warnings", 0),
            "events_total": q.get("events_total", 0),
            "malformed_events": q.get("malformed_events", 0),
            "duplicate_events_dropped": q.get("duplicate_events_dropped", 0),
            "orphan_events": 0,
            "unknown_disposition_events": conn.execute(
                """SELECT COUNT(*) FROM events
                   WHERE lead_id IS NOT NULL
                     AND event_type IN ('disposition.set','disposition.override')
                     AND disposition_known=0"""
            ).fetchone()[0],
        }
        generate_reports(conn, args.out, disp, quality)
        print(f"Reports written to {args.out}")
    conn.close()


if __name__ == "__main__":
    main()
