# Source Compatibility Strategy

## Status

```text
Sprint: 25.2
Stage: PRE-PRODUCTION
Objective: broad source compatibility without mandatory AI
```

## Product decision

The platform must accept the widest practical range of enterprise and industrial information sources without turning every format into a hardcoded worker path.

Compatibility is expressed through a registry with four levels:

```text
native
optional_dependency
container_expansion
planned
```

This prevents the platform from claiming support that has not been operationally proven.

## Compatibility families

### Text and configuration

```text
.txt .log .cfg .conf .ini .properties
.md .markdown .rst
.html .htm .xhtml
.xml .xsd .xsl .xslt .svg
.json .jsonl .yaml .yml
```

These formats use the text adapter where possible.

### Structured records

```text
.ndjson
.parquet
.avro
```

NDJSON is part of the controlled chunk-artifact path. Parquet and Avro are registered as planned structured adapters and are not reported as native.

### Rich documents

```text
.pdf
.doc .docx .docm .dot .dotx
.odt .rtf
.ppt .pptx .pptm .pps .potx
.odp
.epub
```

PDF is the primary rich-document baseline. Office, OpenDocument, RTF and EPUB formats use optional conversion or extraction dependencies.

### Spreadsheets

```text
.csv .tsv
.xls .xlsx .xlsm .xlsb .xlt .xltx
.ods
```

CSV and TSV may use a controlled textual fallback. Workbook formats retain a dedicated tabular adapter to preserve row, cell and sheet provenance.

### Images

```text
.png .jpg .jpeg .tif .tiff .bmp .webp
.heic .heif
```

Raster image ingestion requires optional OCR. HEIC and HEIF remain planned until conversion support is proven.

### Email

```text
.eml .msg .mbox
```

EML and MSG are optional rich-document inputs. MBOX is treated as a container that expands into individual messages.

### Archives

```text
.zip .tar .tgz .tar.gz .gz .7z
```

Archives are containers, not documents. They must be expanded safely, each entry validated and routed independently, and recursive expansion must have configurable limits.

### Drawings

```text
.dxf .dwg
```

Drawing formats are registered as planned. They require specialized extractors and must not be silently processed as ordinary text.

## Reused implementation ideas

The historical worker assets provide useful implementation patterns:

- preprocessing by source format;
- fallback extraction order;
- PDF header and container validation;
- optional OCR using external tools;
- spreadsheet sheet/table segmentation;
- archive entry routing;
- deterministic chunk artifact generation;
- controlled NDJSON validation.

The following historical behavior is not reused as product architecture:

- fixed filesystem paths;
- direct database access from extractors;
- direct Qdrant writes;
- mandatory embedding model loading;
- fixed infrastructure addresses;
- hardcoded business-oriented spreadsheet profiles;
- monolithic subprocess routing.

## Text adapter baseline

`TextIngestionAdapter` is the first real normalized adapter. It:

- consumes bytes rather than fixed local paths;
- detects source format through the compatibility registry;
- decodes UTF-8, UTF-16, Windows-1252 and Latin-1;
- normalizes plain text, Markdown, HTML, XML, JSON, YAML-like text, CSV and TSV;
- generates deterministic overlapping chunks;
- records encoding, format and provenance;
- never generates embeddings;
- never writes to a vector store;
- never invokes an LLM.

CSV and TSV textual fallback exists for maximum compatibility, while the dedicated spreadsheet adapter remains preferred for full tabular provenance.

## Routing policy

1. Extension and media type are evaluated together.
2. Exact agreement has priority.
3. Unsupported formats are rejected explicitly.
4. Ambiguous formats are rejected rather than guessed.
5. Optional dependency formats are only enabled when runtime capability checks pass.
6. Planned formats remain visible in administration but cannot be activated.
7. Container formats are expanded before document routing.

## Security and resource controls

Archive and complex-document ingestion must eventually enforce:

- maximum source size;
- maximum extracted size;
- maximum entry count;
- maximum nesting depth;
- decompression-ratio limits;
- execution timeout;
- isolated workspace;
- filename normalization;
- path traversal prevention;
- checksum validation;
- encrypted-file policy;
- malware scanning hook;
- deterministic cleanup.

## Current verified scope

Implemented in this work package:

- broad compatibility registry;
- more than 30 source-format definitions;
- more than 60 extensions;
- native, optional, container and planned status separation;
- real byte-based text adapter;
- HTML cleanup;
- XML cleanup;
- JSON normalization;
- CSV and TSV fallback;
- deterministic chunks without AI.

Not yet operationally proven:

- Office conversion;
- EPUB extraction;
- OCR execution;
- email attachment expansion;
- archive expansion;
- Parquet and Avro extraction;
- DWG and DXF extraction.

Those capabilities remain explicit subsequent adapter work rather than being represented as complete.
