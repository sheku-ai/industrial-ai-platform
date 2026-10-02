# Document Service

Foundation service for Sprint 2.

## Purpose

Manage document governance, document types, metadata schemas, collections, categories, tags, lifecycle states, and access scopes.

## Core objects

- document_types
- metadata_schemas
- metadata_fields
- document_collections
- documents
- document_versions
- categories
- tags
- document_permissions

## Design principle

Documents must not depend on hard-coded fields. Metadata is defined dynamically per document type.
