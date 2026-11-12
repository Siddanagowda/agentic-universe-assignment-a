import sqlite3
from pathlib import Path

DDL = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS leads (
 id INTEGER PRIMARY KEY,
 workflow_id TEXT NOT NULL,
 phone_hash TEXT NOT NULL,
 phone_cipher TEXT NOT NULL,
 customer_name_cipher TEXT,
 external_ref TEXT NOT NULL,
 batch_id TEXT NOT NULL,
 attributes_json TEXT NOT NULL DEFAULT '{}',
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(workflow_id, phone_hash)
);
CREATE INDEX IF NOT EXISTS idx_leads_ref ON leads(workflow_id, external_ref);
CREATE TABLE IF NOT EXISTS events (
 id INTEGER PRIMARY KEY,
 event_id TEXT NOT NULL UNIQUE,
 workflow_id TEXT NOT NULL,
 event_type TEXT NOT NULL,
 call_id TEXT,
 occurred_at TEXT NOT NULL,
 phone_hash TEXT,
 payload_json TEXT NOT NULL DEFAULT '{}',
 raw_json TEXT NOT NULL,
 lead_id INTEGER NULL REFERENCES leads(id),
 disposition_known INTEGER NOT NULL DEFAULT 1,
 ingested_drop TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_call ON events(call_id);
CREATE INDEX IF NOT EXISTS idx_events_lead ON events(lead_id);
CREATE INDEX IF NOT EXISTS idx_events_phone ON events(workflow_id, phone_hash);
CREATE TABLE IF NOT EXISTS processed_files (
 path TEXT PRIMARY KEY,
 content_sha256 TEXT NOT NULL,
 processed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS rejections (
 id INTEGER PRIMARY KEY,
 workflow_id TEXT NOT NULL,
 batch_id TEXT NOT NULL,
 row_number INTEGER NOT NULL,
 reason TEXT NOT NULL,
 UNIQUE(workflow_id,batch_id,row_number,reason)
);
CREATE TABLE IF NOT EXISTS counters (
 name TEXT PRIMARY KEY,
 value INTEGER NOT NULL
);
"""


def connect(path):
    path = str(path)
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(DDL)
    return conn
