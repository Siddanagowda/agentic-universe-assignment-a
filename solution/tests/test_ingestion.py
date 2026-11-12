import csv, json
from pathlib import Path
from src.db import connect
from src.ingest import ingest_lead_file, ingest_event_file, reconcile_events
from src.report import load_dispositions, generate_reports
from src.security import decrypt

ROOT = Path(__file__).resolve().parents[2]


def schema():
    return json.loads(
        (ROOT / "assignment-a-data/schemas/motor_renewal.json").read_text()
    )


def test_lead_idempotency_and_pii(tmp_path):
    f = tmp_path / "batch_001.csv"
    f.write_text(
        "customer_name,phone,policy_number,premium_amount\nAsha,9876543210,P1,Rs 100\nAsha,9876543210,P1,Rs 200\n,9876543211,P2,100\n"
    )
    db = connect(":memory:")
    c = ingest_lead_file(db, f, schema(), "drop_1")
    assert c["rows"] == 3 and c["duplicates"] == 1 and c["rejected"] == 1
    c2 = ingest_lead_file(db, f, schema(), "drop_1")
    assert c2["skipped"]
    row = db.execute("select * from leads").fetchone()
    assert "9876543210" not in row["phone_cipher"]
    assert decrypt(row["phone_cipher"]) == "+919876543210"
    assert row["batch_id"] == "batch_001"


def test_orphan_reconciles_after_lead(tmp_path):
    db = connect(":memory:")
    ev = tmp_path / "events.jsonl"
    ev.write_text(
        json.dumps(
            {
                "event_id": "e1",
                "event_type": "call.initiated",
                "workflow_id": "motor_renewal",
                "call_id": "c1",
                "occurred_at": "2026-10-01T10:00:00+05:30",
                "phone": "9876543210",
                "payload": {},
            }
        )
        + "\n"
    )
    disp = {"motor_renewal": {"renewed"}}
    ingest_event_file(db, ev, disp, "drop_1")
    reconcile_events(db)
    assert (
        db.execute("select count(*) from events where lead_id is null").fetchone()[0]
        == 1
    )
    lf = tmp_path / "batch_001.csv"
    lf.write_text("customer_name,phone,policy_number\nAsha,9876543210,P1\n")
    ingest_lead_file(db, lf, schema(), "drop_2")
    reconcile_events(db)
    assert (
        db.execute("select count(*) from events where lead_id is not null").fetchone()[
            0
        ]
        == 1
    )


def test_override_link_by_call_id(tmp_path):
    db = connect(":memory:")
    lead = tmp_path / "batch_001.csv"
    lead.write_text("customer_name,phone,policy_number\nAsha,9876543210,P1\n")
    ingest_lead_file(db, lead, schema(), "drop_1")
    ev = tmp_path / "events.jsonl"
    base = {
        "workflow_id": "motor_renewal",
        "call_id": "c1",
        "occurred_at": "2026-10-01T10:00:00Z",
        "payload": {},
    }
    a = dict(base, event_id="e1", event_type="call.initiated", phone="9876543210")
    b = dict(
        base,
        event_id="e2",
        event_type="disposition.override",
        payload={"disposition_code": "renewed"},
    )
    ev.write_text(json.dumps(a) + "\n" + json.dumps(b) + "\n")
    ingest_event_file(db, ev, {"motor_renewal": {"renewed"}}, "drop_1")
    reconcile_events(db)
    assert (
        db.execute("select lead_id from events where event_id='e2'").fetchone()[0]
        is not None
    )
