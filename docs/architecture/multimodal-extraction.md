# Multimodal Extraction Architecture

## Status

```text
Sprint: 25.3
Stage: PRE-PRODUCTION
Provider execution: DISABLED
OCR execution: NOT YET ENABLED
Visual model execution: NOT YET ENABLED
```

## Objective

Prepare the platform for rich-document extraction, OCR and image understanding without making any specific provider mandatory and without increasing baseline runtime load.

## Contracts

The platform now defines four independent boundaries:

```text
DocumentExtractionProvider
OcrProvider
ImageUnderstandingProvider
VisualContentPolicy
```

This separation prevents MarkItDown, Tesseract, a vision model or a cloud API from becoming the platform architecture.

## Processing profiles

### Economy

- primary extraction;
- OCR only when text is insufficient or the image is text-oriented;
- no image description;
- no network providers;
- bounded to 20 OCR pages and 180 seconds by default.

This is the recommended default profile.

### Balanced

- primary extraction;
- adaptive OCR;
- image understanding for relevant diagrams, charts, screenshots and photographs;
- local providers preferred;
- no network access by default;
- bounded to 50 OCR pages and 20 visual images.

### High fidelity

- broader OCR and visual coverage;
- larger page and image budgets;
- network providers may be enabled;
- intended only for explicit policies and controlled workloads.

### Offline strict

- no network access;
- all providers must be local;
- OCR and image understanding remain optional capabilities;
- processing continues with reduced results if a local provider is unavailable.

## Capability states

Every provider reports one of:

```text
available
unavailable
disabled
degraded
```

An unavailable or disabled optional provider does not make the core platform unhealthy.

## Resource budgets

Every processing policy defines explicit limits for:

- source bytes;
- pages;
- extracted images;
- OCR pages;
- visually described images;
- execution timeout;
- retry attempts.

These budgets are enforced before provider-specific implementations are activated.

## Visual content policy

The policy decides separately whether to run OCR and image understanding.

### Always skipped

- duplicate images;
- decorative images;
- repeated logos;
- invalid image dimensions.

### OCR candidates

- scanned text;
- screenshots;
- rasterized tables;
- handwriting;
- pages with insufficient extracted text.

### Visual-understanding candidates

- diagrams;
- charts;
- photographs;
- screenshots;
- unknown but potentially relevant images.

OCR and visual understanding may both run when an image contains text and relevant visual structure.

## Normalized results

### Document extraction

Returns:

- normalized Markdown;
- extracted images;
- provider identifier;
- metrics;
- controlled error status.

### OCR

Returns:

- recognized text;
- confidence;
- language;
- bounding boxes;
- provider identifier;
- metrics and controlled errors.

### Image understanding

Returns:

- caption;
- detailed description;
- structured observations;
- confidence;
- provider identifier;
- metrics and controlled errors.

OCR text and image descriptions remain separate evidence fields.

## Current implementation boundary

This sprint introduces contracts, policies and tests only. It does not yet install or execute:

- MarkItDown;
- Tesseract;
- PDF page rendering;
- Florence-2 or another vision model;
- cloud document intelligence;
- GPU workers.

The next work package can implement a MarkItDown provider against these contracts without changing the platform-level API.

## Acceptance criteria

- four processing profiles exist;
- each profile has explicit resource budgets;
- local-only policy cannot enable network providers;
- duplicate and decorative images are skipped;
- OCR and visual description decisions are independent;
- disabled providers are representable without runtime failure;
- no provider is mandatory for core platform readiness.
