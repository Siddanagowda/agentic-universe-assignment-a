import json
from pathlib import Path
from src.db import connect
from src.ingest import ingest_lead_file, ingest_event_file, reconcile_events
from src.report import load_dispositions, generate_reports

ROOT = Path(__file__).resolve().parents[2]


def test_report_contract(tmp_path):
    db = connect(":memory:")
    lf = tmp_path / "batch_001.csv"
    lf.write_text("customer_name,phone,policy_number\nAsha,9876543210,P1\n")
    schema = json.loads(
        (ROOT / "assignment-a-data/schemas/motor_renewal.json").read_text()
    )
    ingest_lead_file(db, lf, schema, "drop_1")
    ev = tmp_path / "events.jsonl"
    events = [
        {
            "event_id": "e1",
            "event_type": "call.initiated",
            "workflow_id": "motor_renewal",
            "call_id": "c1",
            "occurred_at": "2026-10-01T10:00:00+05:30",
            "phone": "9876543210",
            "payload": {},
        },
        {
            "event_id": "e2",
            "event_type": "call.connected",
            "workflow_id": "motor_renewal",
            "call_id": "c1",
            "occurred_at": "2026-10-01T10:01:00+05:30",
            "phone": "9876543210",
            "payload": {},
        },
        {
            "event_id": "e3",
            "event_type": "disposition.set",
            "workflow_id": "motor_renewal",
            "call_id": "c1",
            "occurred_at": "2026-10-01T10:02:00+05:30",
            "phone": "9876543210",
            "payload": {"disposition_code": "renewed"},
        },
    ]
    ev.write_text("\n".join(json.dumps(x) for x in events) + "\n")
    ingest_event_file(db, ev, {"motor_renewal": {"renewed"}}, "drop_1")
    reconcile_events(db)
    disp = load_dispositions(ROOT / "assignment-a-data/schemas/dispositions.csv")
    generate_reports(db, tmp_path / "reports", disp, {"lead_rows_total": 1})
    assert (tmp_path / "reports" / "batch_summary.csv").exists()
    row = (tmp_path / "reports" / "lead_report.csv").read_text().splitlines()[1]
    assert "+91******3210" in row and "completed" in row and "renewed" in row
