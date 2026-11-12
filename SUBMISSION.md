# Submission

## Candidate

- **Name:** Siddana Gowda
- **Assignment chosen:** A (Data)
- **Time spent:** 5 hours

## How to Run

Run the following commands from the repository root using a Python virtual environment:

```bash
pip install -r solution/requirements.txt

python assignment-a-data/tools/generate_data.py --seed 42 --scale small --out data

python -m solution.src.cli ingest data/drop_1

python -m solution.src.cli ingest data/drop_2

python -m solution.src.cli report --out reports

pytest solution/tests -q
```

## Design

SQLite stores leads separately from an append-only interaction ledger.

Lead identity is `(workflow_id, HMAC(phone))`. Customer names and canonical phone numbers are encrypted using Fernet. Events are unique by `event_id`, retained as raw JSON, and linked to leads using the workflow and keyed phone digest.

Phone-less disposition overrides are reconciled through call IDs. Reports are derived from the event ledger rather than mutating event history.

## Decisions & Assumptions

| Decision | Why | Alternative considered |
|---|---|---|
| SQLite | Simple, reproducible local setup | PostgreSQL |
| Fernet + HMAC | Recoverable PII encryption and deterministic matching | Plaintext phone |
| UTC storage, IST reporting | Unambiguous event ordering and local reporting dates | Store local wall-clock time |
| File path + SHA-256 idempotency | Prevents accidental reprocessing and detects changed input | Reprocess every run |
| Retain unresolved events and reconcile later | Supports events arriving before their lead records | Drop or permanently quarantine |

## Failure Modes Considered

- Repeated ingestion of an unchanged file is a no-op.
- Duplicate event IDs are dropped.
- Malformed JSON lines are counted.
- Invalid lead rows are rejected without exposing PII in rejection reports.
- Unknown dispositions are excluded from effective disposition calculations.
- Orphan events are retained and can be linked after later lead ingestion.
- A changed file at an already-ingested path is rejected.

## Testing

Unit and integration tests cover:

- Phone-number normalization and invalid phone numbers.
- Supported date formats and impossible dates.
- Currency and amount parsing.
- Naive timestamps interpreted as IST.
- Lead-ingestion idempotency.
- PII encryption and ciphertext storage.
- Late-arriving lead reconciliation.
- Call-ID-based override linking.
- Report generation and output structure.

## Results

### Local execution

Successfully executed the assignment using the supplied data generator with seed `42` and scale `small`.

| Metric | Result |
|---|---:|
| Lead rows received | 2,057 |
| Lead rows rejected | 108 |
| Duplicate lead rows merged | 57 |
| Field warnings | 122 |
| Event lines received | 8,745 |
| Malformed events | 8 |
| Duplicate events dropped | 237 |
| Orphan events | 462 |
| Unknown disposition events | 19 |
| Accepted unique leads in batch summary | 1,892 |

### Ingestion results

| Batch | Leads reported | Events processed | Reconciliation |
|---|---:|---:|---|
| drop_1 | 1,515 | 4,247 | Successful |
| drop_2 | 542 | 4,498 | Successful |

### Generated reports

Successfully generated all five expected report files:

1. `batch_summary.csv`
2. `daily_overview.csv`
3. `lead_report.csv`
4. `rejections.csv`
5. `data_quality.json`

### Data consistency verification

The accepted unique lead count matches the batch summary:

`2,057 - 108 - 57 = 1,892`

The batch summary contains 1,892 leads across its workflow and batch combinations.

### Automated tests

Executed:

```bash
pytest solution/tests -q
```

Result:

```text
....................... [100%]
23 passed in 0.14s
```

All 23 tests passed with zero failures.

**Validation scope:** The above results are from the local run using seed `42`. Additional fresh-seed validation and comparison against unseen datasets remain to be completed.

## If I Had Another Day

1. Validate against multiple unseen seeds and compare all five generated outputs.
2. Improve large-scale ingestion using batched inserts and indexed reconciliation.
3. Add SQL-based report aggregation and database schema migrations.
4. Add property-based tests for messy CSV headers, values, and edge cases.
