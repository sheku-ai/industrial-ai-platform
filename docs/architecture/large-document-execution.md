# Large Document Execution

## Status

```text
Stage: PRE-PRODUCTION
Default action: PARTITION, NOT DISCARD
```

## Decision

Documents that exceed the normal extraction budget must not be rejected automatically when they can be processed safely in segments.

```text
register
  -> inspect
  -> classify size and complexity
  -> create segment plan
  -> process bounded segments
  -> persist checkpoints
  -> expose partial availability
  -> resume after interruption
  -> consolidate final result
```

## Default thresholds

The current baseline budget is:

```text
100 MB source size
500 pages
100 extracted images
50 OCR pages
20 visually described images
300 seconds
3 attempts
```

These are configurable policy defaults, not absolute product limits.

## Large-document policies

```text
partition
reduced_profile
metadata_only
manual_approval
reject
```

`partition` is the recommended default when the format supports bounded processing.

`reject` is reserved for absolute security, quota or technical limits.

## Segmentation strategies

### PDF

- inspect encryption and page count first;
- split logically by page ranges;
- process 25 to 100 pages per segment according to policy;
- persist text, images and provenance per page range;
- enqueue OCR only for pages that require it;
- consolidate after all required segments complete.

### Word-processing and presentation documents

- segment by section, slide or conversion artifact;
- persist primary text before visual enrichment;
- process embedded images separately;
- retain section, slide and relationship provenance.

### Spreadsheets

- inspect workbook structure;
- process sheet by sheet;
- segment large sheets by row ranges;
- preserve sheet, row and cell provenance;
- avoid loading all rows into memory when streaming readers are available.

### Email containers

- process the message body first;
- register attachments as related document versions;
- process attachments independently;
- preserve message, inline-image and attachment relationships.

### Archives

- list entries without full extraction where possible;
- enforce entry count, nesting depth, expanded-size and compression-ratio limits;
- process entries independently;
- preserve parent-container provenance;
- route protected containers to human review.

## Source access contract

The current byte-payload contract is suitable for bounded files. Large-document execution must evolve toward a streaming source handle:

```text
SourceHandle
  source_reference
  size_bytes
  checksum
  open_stream()
  read_range()
  materialize_bounded_workspace()
```

Object storage remains payload-only. PostgreSQL remains the lifecycle and checkpoint source of truth.

## Segment checkpoint

Each segment requires a durable checkpoint containing:

```text
segment_id
segment_type
start boundary
end boundary
status
attempt
checksum
provider
chunk count
artifact references
started_at
completed_at
error code
```

A restart resumes from incomplete or retryable segments rather than reprocessing the entire document.

## Partial availability

Large documents may become searchable before visual enrichment is complete.

```text
registered
inspecting
partitioned
extracting
partially_available
enriching
completed
completed_with_warnings
failed
pending_human_review
```

Primary text and lexical retrieval should become available as soon as validated segments are persisted.

## Queue isolation

Recommended queues:

```text
ingestion-cpu
heavy-document
document-conversion
ocr-cpu
vision-gpu
cloud-document
human-review
```

A heavy document must not block ordinary text ingestion.

## Backpressure

The runtime must apply configurable limits for:

- concurrent large documents;
- concurrent segments per document;
- memory per worker;
- workspace disk usage;
- provider timeout;
- OCR and vision budgets;
- organization quota;
- global queue depth.

## Recovery behavior

- persist after every successful segment;
- retry only failed or retryable segments;
- preserve completed segment artifacts;
- keep idempotency at segment and document level;
- consolidate only from validated segment outputs;
- clean isolated workspace after each segment.

## Security limits

A document is rejected or quarantined only when it:

- exceeds an absolute configured maximum;
- cannot be segmented safely;
- violates quota or retention policy;
- contains unsafe archive paths;
- exceeds decompression limits;
- fails malware policy;
- remains structurally corrupt after controlled inspection.

Password-protected and encrypted sources are routed to `pending_human_review`, not discarded.

## Planned implementation slices

```text
25.6B.1 SourceHandle and inspection contracts
25.6B.2 Segment plans and checkpoints
25.6B.3 PDF page-range execution
25.6B.4 partial availability and consolidation
25.6B.5 queue isolation and backpressure
25.6B.6 restart and resume evidence
```
