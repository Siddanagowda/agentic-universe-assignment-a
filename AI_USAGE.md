# AI Usage Disclosure

## Tools Used
- ChatGPT

## What I Used Them For
- Reviewed and interpreted the assignment requirements.
- Assisted with designing the data ingestion and reporting architecture.
- Scaffolded the Python modules for CSV and JSONL ingestion, data normalization, validation, deduplication, reconciliation, and reporting.
- Assisted with implementing SQLite database operations, encryption, and secure phone-number hashing.
- Drafted unit and integration tests.
- Helped debug implementation issues and explain the code and its design decisions.

## What I Wrote or Decided Myself
- Selected SQLite as the database solution.
- Reviewed the proposed architecture and implementation.
- Executed the application locally and examined the generated reports.
- Reviewed the data-quality metrics and lead-level reporting output.
- Ran the automated test suite and evaluated the results.
- Reviewed the implementation to understand its functionality and design decisions.

## Where the AI Was Wrong or Unhelpful
- The initial local verification used a simplified fixture dataset, which was not sufficient to establish compatibility with the original assignment data.
- I subsequently ran the implementation using the assignment's supplied data generator and inspected the resulting reports.
- I recognized that passing automated tests alone does not guarantee complete compliance with every assignment requirement, so further specification-level verification is necessary.

## How I Verified AI-Generated Code
- Installed dependencies in a local Python virtual environment.
- Generated assignment data using the supplied generator with seed `42` and scale `small`.
- Successfully ingested both `drop_1` and `drop_2`.
- Generated the reporting outputs locally.
- Inspected `data_quality.json`, `lead_report.csv`, `batch_summary.csv`, `daily_overview.csv`, and `rejections.csv`.
- Verified that the accepted lead count reconciles with the batch summary: 2,057 total rows - 108 rejected rows - 57 duplicate rows merged = 1,892 leads.
- Executed the automated test suite using `pytest solution/tests -q`, with **23 tests passing and zero failures**.

Additional verification with fresh random seeds and further edge-case testing should be completed before final submission.
