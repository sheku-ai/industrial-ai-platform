# Rich Document Adapter

## Status

```text
Sprint: 25.5
Stage: PRE-PRODUCTION
Primary objective: deterministic provider orchestration
OCR execution: not yet enabled
Visual understanding: not yet enabled
```

## Decision

Rich-document ingestion is implemented as an orchestration layer over independent extraction providers.

The adapter does not parse every format itself. It selects an ordered provider chain, records every attempt and returns the first acceptable result.

## Current provider chains

### PDF

```text
native-pdf
  -> markitdown
```

The native PDF provider is attempted first because it is lightweight, local and already part of the core API dependency set. MarkItDown is used as fallback when native extraction returns no useful text or fails.

### EML

```text
native-eml
  -> markitdown
```

The native EML provider uses the Python standard-library MIME parser and extracts common headers and the plain-text body. Attachment expansion remains a later work package.

### DOC, DOCX, ODT, RTF, PPT, PPTX, ODP, EPUB, MSG and raster images

```text
markitdown
```

These formats currently depend on the optional MarkItDown profile. A disabled or unavailable provider produces a controlled failure without affecting platform readiness.

## Native PDF provider

The provider:

- consumes bytes;
- enforces source-size and page-count budgets;
- extracts page text with `pypdf`;
- preserves page headings in Markdown;
- records empty-page count;
- reports when OCR may be required;
- never invokes OCR, LLMs, embeddings or network services.

## Native email provider

The provider:

- consumes EML bytes;
- parses Subject, From, To, Cc and Date;
- extracts a plain-text body;
- counts attachments;
- does not yet expand or ingest attachments;
- performs no network or AI calls.

## Fallback rules

1. Resolve the source format through the compatibility registry.
2. Build the provider chain for that format.
3. Execute providers in order.
4. Return the first successful result containing non-empty Markdown.
5. Preserve a partial result when no later provider succeeds.
6. Stop immediately on retryable provider errors.
7. Record every provider attempt.
8. Return a controlled aggregate failure when all providers fail or are unavailable.

## Metrics

Successful or partial results include:

```text
selected_provider
provider_attempts
fallback_used
```

Each attempt records:

```text
provider_key
status
error_code
```

This makes provider selection observable without exposing implementation internals to the document model.

## Resource strategy

The adapter reduces resource use by:

- preferring native PDF extraction before MarkItDown;
- using the standard-library EML parser before MarkItDown;
- avoiding OCR until the OCR work package;
- avoiding GPU and visual models;
- respecting existing source and page budgets;
- not loading optional providers when disabled.

## Current limitations

Not yet implemented:

- PDF image extraction;
- OCR fallback;
- embedded-image classification;
- EML attachment expansion;
- HTML email body fallback;
- MSG native parser;
- provider capability API;
- persisted provider configuration;
- real fixture E2E for PDF, DOCX, PPTX and EML.

These limits are explicit and belong to subsequent work packages.
