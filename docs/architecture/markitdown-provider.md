# MarkItDown Provider

## Status

```text
Sprint: 25.4
Stage: PRE-PRODUCTION
Provider role: optional rich-document extraction
Plugins: disabled
Network access: disabled by policy
GPU: not required
```

## Decision

Microsoft MarkItDown is integrated as an optional extraction provider behind the platform `DocumentExtractionProvider` contract.

It is not part of the mandatory API requirements and it does not define platform routing, persistence, security, metadata or indexing.

## Isolation

The API invokes MarkItDown through a dedicated Python subprocess:

```text
MarkItDownProvider
  -> app.services.markitdown_runner
  -> MarkItDown.convert_stream()
  -> normalized Markdown result
```

The subprocess boundary provides:

- execution timeout;
- explicit return codes;
- separation from API process memory;
- controlled stdin/stdout contract;
- no direct database or object-storage access;
- deterministic failure reporting.

## Security constraints

- use `convert_stream()` rather than unrestricted URL conversion;
- never pass untrusted remote URLs;
- plugins remain disabled;
- no LLM client is configured;
- no network provider is configured;
- source-size budget is enforced before execution;
- the provider does not open PostgreSQL, Qdrant or MinIO connections;
- extraction output is treated as untrusted text and validated downstream.

## Optional installation

Core API installation:

```powershell
pip install -r apps/api/requirements.txt
```

Rich-document profile:

```powershell
pip install -r apps/api/requirements-markitdown.txt
```

The optional profile includes format-specific dependencies for:

```text
PDF
DOCX
PPTX
XLSX
XLS
Outlook messages
```

It intentionally does not install every MarkItDown optional feature.

## Runtime states

```text
disabled     configuration does not enable the provider
unavailable  enabled, but package is not installed
available    enabled and package can be imported
degraded     reserved for runtime capability diagnostics
```

Disabled and unavailable states do not make the core platform unhealthy.

## Result behavior

The provider returns:

- `skipped/provider_disabled` when disabled;
- `skipped/provider_unavailable` when not installed;
- `failed/source_too_large` before execution when the budget is exceeded;
- `retryable/provider_timeout` when conversion exceeds its timeout;
- `failed/provider_execution_failed` on subprocess errors;
- `partial/empty_extraction` when conversion returns no content;
- `succeeded` with Markdown and metrics when extraction completes.

## Current scope

Implemented:

- optional dependency profile;
- package availability detection;
- isolated subprocess runner;
- stream-based conversion;
- plugins disabled;
- source-size limit;
- timeout;
- normalized success and failure results;
- no AI, OCR, vector or database behavior.

Not yet implemented:

- activation from persisted platform configuration;
- provider capability endpoint;
- rich-document fallback orchestration;
- image extraction;
- OCR enrichment;
- document-level E2E with real PDF, DOCX and PPTX fixtures.

These belong to the following work packages.
