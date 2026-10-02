# SHEKU Security Policy

## Scope

This policy applies to the SHEKU product and its maintained 1.6.x release line.

SHEKU is currently in pre-production/product stabilization. Security findings that affect authentication, authorization, organization isolation, secret handling, persistence integrity, auditability or production deployment are treated as release-relevant defects.

## Reporting a vulnerability

Do not disclose suspected vulnerabilities through a public issue.

Report security findings privately to the repository owner or through GitHub's private security reporting / Security Advisory mechanism when available for this repository.

Include, when possible:

- affected version or commit;
- affected component or endpoint;
- reproduction conditions;
- expected versus observed behavior;
- security impact;
- whether organization isolation, authentication, authorization or persisted data can be affected;
- any evidence required to reproduce the issue without including production secrets.

## Sensitive information

Do not include passwords, tokens, API keys, private certificates, production credentials, customer data or other secrets in issues, logs, screenshots or validation artifacts.

Credentials and secrets must be referenced through governed configuration/secret boundaries and must not be committed to source control.

## Security invariants

Security changes must preserve SHEKU product invariants:

- organization isolation is enforced at backend boundaries;
- PostgreSQL remains authoritative for governed state;
- identity/session state is persisted in the identity authority;
- authorization applies to source data and derived knowledge eligibility;
- production configuration fails closed;
- AI and external providers do not bypass security or knowledge-governance boundaries;
- audit and runtime evidence must not be altered to hide a defect;
- secret material must not be exposed through API responses, logs or documentation.

## Security validation

A security defect is corrected in the responsible runtime or configuration boundary first. Acceptance criteria or Product Acceptance must not be weakened to make a failing security gate pass.

Production-readiness security requirements are maintained in `docs/deployment/PRODUCTION_READINESS.md`.

## Supported versions

The active stabilization line is `1.6.x`. Historical branches and development snapshots are retained for traceability but are not implied to receive security fixes unless explicitly designated as supported.
