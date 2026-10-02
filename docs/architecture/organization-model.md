# Organization Model

The organization model defines the business and operational structure used by documents, permissions, search scopes, and AI context.

## Core hierarchy

```text
Company
  -> Business Area
    -> Department
      -> Team
  -> Country
    -> Site or Plant
      -> System
        -> Asset
```

## Key principle

Use hierarchy plus relationships.

A plant can be operated by one area, technically governed by another area, and audited by a third area. This avoids a rigid tree model.

## Core entities

- Company
- Organization Unit
- Relationship
- Area
- Department
- Country
- Site
- Plant
- System
- Asset

## Relationship examples

- operates
- owns
- supports
- audits
- governs
- maintains
