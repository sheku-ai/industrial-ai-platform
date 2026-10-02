# Effective Platform Configuration

## Purpose

The platform exposes its effective non-secret runtime configuration through:

```text
GET /platform/configuration
```

This contract is intended for operational verification, diagnostics and administrative tooling. It must never expose credentials or secret material.

## Exposed configuration

The response includes:

- application name and version;
- effective portal port;
- effective CORS origins;
- database driver, host, port and database name;
- object-storage enablement and endpoint host/port;
- object-storage region and configuration state;
- ingestion workspace and source-size limit;
- worker and optional feature flags;
- operational-health thresholds;
- build commit;
- database revision;
- configuration revision;
- provider-execution state.

## Redaction rules

The contract never returns:

- database usernames;
- database passwords;
- complete database URLs;
- object-storage access keys;
- object-storage secret keys;
- tokens;
- signing material;
- credentials embedded in endpoints.

Credential presence is represented only as a boolean configuration state.

## Example

```json
{
  "app_name": "Industrial AI Platform API",
  "app_version": "1.3.1",
  "portal_port": 3000,
  "cors_origins": [
    "http://localhost:3100",
    "http://127.0.0.1:3100"
  ],
  "database": {
    "configured": true,
    "driver": "postgresql+psycopg",
    "host": "postgres",
    "port": 5432,
    "database": "industrial_ai"
  },
  "object_storage": {
    "enabled": false,
    "endpoint_host": null,
    "endpoint_port": null,
    "secure": false,
    "region": "us-east-1",
    "bucket_configured": false,
    "credentials_configured": false
  },
  "provider_execution_enabled": false
}
```

## Architectural position

This endpoint reports effective runtime state. It does not replace PostgreSQL-backed administrative configuration, environment management or secret management.

AI and optional infrastructure remain service-layer capabilities. Disabled optional services must be represented as disabled rather than treated as platform failures.

## Authentication proxy configuration

The effective deployment must explicitly govern forwarded client-address evidence:

- `AUTH_TRUSTED_PROXY_NETWORKS`: comma-separated immediate trusted proxy CIDRs; empty means forwarded headers are ignored.
- `AUTH_FORWARDED_IP_HEADERS`: ordered accepted header names, normally `forwarded,x-forwarded-for`.

These values contain no credentials but should be reviewed as security-sensitive topology configuration. Invalid networks or malformed forwarding chains fail safely to the direct peer address.
