# SHEKU Core No-AI E2E

## Purpose

This E2E validates the persistent SHEKU control-plane/core baseline independently of AI services, embeddings and vector retrieval.

It is not a complete document-lifecycle acceptance test because it intentionally omits object-storage and ingestion profiles. Full document/storage/processing readiness is validated through the relevant Product Acceptance and lifecycle evidence.

## Command

From the repository root:

```powershell
python scripts/e2e_core_platform.py
```

The script name is a retained technical identifier; it does not define the product name.

## Local endpoints

```text
API:    http://127.0.0.1:8000
Portal: http://127.0.0.1:3000
```

## Flow

The script performs the following sequence:

1. stop the complete Compose stack without removing PostgreSQL volumes;
2. start PostgreSQL, migrator, API, scheduler and portal;
3. verify API readiness and portal availability;
4. create a generic organization resource through the supported API;
5. retrieve the resource through the API;
6. verify the row directly in PostgreSQL;
7. stop and recreate the stack while preserving the database volume;
8. retrieve the same resource after restart;
9. verify the row again directly in PostgreSQL;
10. delete the temporary resource;
11. perform complete shutdown;
12. write machine-readable evidence.

## Optional services excluded from this harness

The harness explicitly excludes:

```text
embeddings
vector retrieval
AI provider execution
object-storage-dependent document flow
```

This proves a bounded no-AI control-plane capability only. It must not be used as evidence that storage-dependent product capabilities are ready when object storage is not running.

## Evidence

Evidence is written to:

```text
runtime/evidence/core-platform-e2e.json
```

A successful result contains evidence that the persisted organization resource survives restart and that AI was not required.

## Safety

The script creates a unique temporary resource and removes it after validation.

It does not remove named PostgreSQL volumes. Existing product data remains intact.

If execution fails, the script attempts resource cleanup and complete stack shutdown before writing failure evidence.
