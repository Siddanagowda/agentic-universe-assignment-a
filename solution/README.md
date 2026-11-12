# Agentic Universe – Assignment A Solution

**Python 3.11+ · SQLite · pytest**

This implementation ingests workflow-specific lead CSV files and JSONL interaction events, protects personally identifiable information (PII) using Fernet encryption and keyed HMAC phone digests, reconciles late-arriving events, and generates five reports.

## Setup

Create and activate a virtual environment.

```bash
python -m venv .venv
```

**Windows (PowerShell):**

```powershell
.venv\Scripts\Activate.ps1
```

**macOS/Linux:**

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r solution/requirements.txt
```

### Encryption key configuration

A local `.pii_key` is generated on the first run and ignored by Git.

For repeatable deployments, set `AU_PII_KEY` to a Fernet key generated using:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Back up this key securely. Encrypted PII cannot be recovered without the corresponding key.

## Generate and Run

Generate the assignment dataset:

```bash
python assignment-a-data/tools/generate_data.py --seed 42 --scale small --out data
```

Ingest the first batch:

```bash
python -m solution.src.cli ingest data/drop_1
```

Ingest the second batch:

```bash
python -m solution.src.cli ingest data/drop_2
```

Generate reports:

```bash
python -m solution.src.cli report --out reports
```

Use a different `--seed` value for additional validation.

Generated data, report directories, SQLite databases, `.pii_key`, and `.env` files are excluded from Git.

## Tests

Run the automated test suite:

```bash
pytest solution/tests -q
```

The current local test suite contains 23 tests, all of which passed during verification.

## Design

### 1. Lead storage and identity

- The `leads` table uses a unique `(workflow_id, phone_hash)` identity.
- Phone numbers and customer names are encrypted at rest.
- Phone lookup uses a keyed HMAC digest, allowing deterministic matching without storing plaintext phone numbers for lookup.

### 2. Event ledger

- The `events` table is append-only with uniqueness enforced through `event_id`.
- Raw JSON and event payloads are retained.
- Derived lead links can be updated during reconciliation when late-arriving lead records become available.

### 3. Idempotent ingestion

- The `processed_files` table tracks file paths and content hashes.
- Re-ingesting the same unchanged file is a no-op.
- A changed file at an already-ingested path is rejected instead of being silently double-counted.

### 4. Disposition handling

- Supervisor overrides are stored as new ledger events rather than modifying historical events.
- Reporting selects the latest override when one exists; otherwise, it selects the latest disposition set.

### 5. Timestamp handling

- Event timestamps are stored in UTC.
- Naive timestamps are interpreted as IST.
- Reporting dates and rendered timestamps are converted to IST.

## Generated Reports

The reporting command generates five outputs:

| Report | Description |
|---|---|
| `batch_summary.csv` | Lead status counts grouped by workflow and batch |
| `daily_overview.csv` | Daily calling activity, connectivity, and successful leads |
| `lead_report.csv` | Individual lead status and call history summary |
| `rejections.csv` | Rejected lead records and their validation reasons |
| `data_quality.json` | Data-quality metrics, duplicate counts, malformed events, and orphan events |

## Assumptions and Limitations

1. The synthetic generator may produce duplicate lead rows whose non-null fields should be merged. The first lead's batch remains its attribution batch.

2. The event ledger retains malformed and duplicate counts in ingestion counters. Malformed JSON lines cannot be stored as structured events.

3. File-level idempotency uses the combination of file path and content hash. Replacing a previously ingested file is rejected; use a new path for a corrected delivery.

4. This is a compact take-home implementation, not a high-throughput streaming service. A production implementation should include schema migrations, managed encryption keys (KMS), structured audit logs, and incremental reconciliation jobs.

## Security

- Never commit `.pii_key`, `.env`, database files, or generated customer data.
- The generated assignment data is synthetic.
- Fernet provides authenticated encryption.
- HMAC digests are keyed and deterministic.
- Protect encryption keys and restrict access to the database and generated reports.

## Local Verification Results

The implementation was locally executed using the supplied data generator with seed `42` and scale `small`.

- Both input batches were successfully ingested.
- All five reports were generated.
- 2,057 lead rows were processed.
- 108 lead rows were rejected.
- 57 duplicate lead rows were merged.
- 8,745 event lines were processed.
- All 23 automated tests passed.

Additional fresh-seed validation and full comparison against the assignment specification should be completed before final submission.
