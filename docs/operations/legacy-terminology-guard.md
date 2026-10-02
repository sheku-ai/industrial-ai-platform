# Legacy Terminology Guard

## Purpose

The platform must remain generic and product-led. Historical implementation terminology must not define executable product code, APIs, UI models or runtime contracts.

## Command

From the repository root:

```powershell
python scripts/check_legacy_terminology.py
```

Machine-readable output:

```powershell
python scripts/check_legacy_terminology.py --json
```

## Scan scope

The guard scans executable product code under:

```text
apps/api/app
apps/admin-portal
scripts
```

Generated, virtual-environment and runtime output directories are excluded.

## Blocked terminology

The initial rules block explicit historical identifiers such as:

```text
ia-om
ia_om
iaom
docs_v2
plant_id
plant_name
plant_code
plant_type
site_id
site_name
site_code
site_type
wind_farm
solar_farm
```

These terms must be replaced with generic platform concepts such as organization, organization node, location node, configurable collection or configurable classification.

## Policy

A finding causes a non-zero exit code. New exceptions are not allowed merely to preserve legacy naming.

When a false positive is identified, the preferred correction is to improve the matching rule without weakening the generic-platform requirement.

Historical documentation and database migration history are not rewritten automatically. The guard focuses on active executable product surfaces.
