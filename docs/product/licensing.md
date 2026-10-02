# SHEKU Licensing Model

## Product decision

SHEKU uses an open-core licensing model with a commercial Enterprise layer.

### SHEKU Community / Core

The reusable Community/Core code distributed from this repository is licensed under the **Apache License 2.0**, subject to the repository `LICENSE` file.

This choice is intended to support:

- commercial and internal use;
- redistribution and modification;
- broad enterprise adoption;
- explicit patent-license terms;
- development of a connector and integration ecosystem.

### SHEKU Enterprise

SHEKU Enterprise components are licensed under a separate **commercial proprietary license**.

Enterprise code, packages, artifacts or services are not automatically covered by the Apache License 2.0 merely because they interoperate with or depend on SHEKU Core.

Commercial terms, support, warranties, distribution rights and Enterprise-specific rights are governed by the applicable commercial agreement.

## Architectural boundary

Licensing must follow the architectural dependency rule:

```text
SHEKU Core / Community  <- may be extended by -  SHEKU Enterprise
```

Core must not require Enterprise components to provide the documented Community/Core baseline.

Enterprise may depend on Core through supported contracts and extension boundaries.

The licensing model must not create two incompatible product architectures.

## Trademark separation

The Apache License 2.0 covers licensed source code and documentation. It does not grant general rights to the SHEKU name, tagline, logos or other brand identifiers.

Trademark and brand usage are governed separately by `TRADEMARKS.md`.

## Repository and packaging rule

Any future Enterprise distribution must make its licensing boundary explicit in repository layout, package metadata and release artifacts.

A file or package must not be represented as Apache-licensed if it is actually an Enterprise proprietary component.

## Release rule

Release documentation must identify whether an artifact belongs to:

- SHEKU Community/Core under Apache License 2.0; or
- SHEKU Enterprise under a commercial proprietary license.

Licensing metadata must be consistent with the files actually distributed.
