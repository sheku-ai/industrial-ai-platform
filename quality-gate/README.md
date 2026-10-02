# Containerized Quality Gate

The Quality Gate is an isolated Compose project named `industrial-ai-quality`. It builds dedicated validator images, starts disposable platform and identity PostgreSQL instances on an internal-only network, applies both official migration chains, and runs backend, portal, dependency, security, and production-image checks.

Run the normal native-architecture gate from any directory:

```bash
./scripts/run-quality-gate.sh
```

Use the release mode only when QEMU/buildx support is available and both `linux/amd64` and `linux/arm64` builds are required:

```bash
./scripts/run-quality-gate.sh --release
```

No host ports, repository mounts, Docker socket mounts, external volumes, pre-production environment files, or pre-production networks are used. Database files live only in container `tmpfs`. The two audit validators use a separate egress network; neither PostgreSQL service is connected to it.

`PASSED` means every blocking gate passed. `FAILED` means at least one blocking gate failed; all remaining gates still run so the report is complete. Root pytest, the security regression, both migrations, workflow-baseline static analysis, portal compilation/lint/build/contracts, the production-only npm audit, native production images, and cleanup are blocking. Expanded backend analysis, the portal editorial audit, the full npm dependency-tree audit, and the pinned Python audit are informational.

The npm validator image intentionally has `NODE_ENV=production`, so audit scope is always explicit: the blocking production audit uses `--omit=dev`, while the informational complete-tree audit uses `--include=dev`. The development-only delta is the complete-tree result minus the production result, both by vulnerable package name and by severity. A boolean npm `fixAvailable` result is recorded as fix availability only; it is not treated as proof of application compatibility.

`pip-audit` fix versions identify releases that address individual advisories. They are not automatically compatible upgrade recommendations. The report preserves all advisory fixes but leaves compatible validated versions empty until dependency constraints and integration compatibility are checked separately.

JSON and Markdown reports are written to `runtime/quality-reports/<commit-sha>.*`. Per-stage logs are retained beside them in `<commit-sha>.logs/`. The entire `runtime/` tree is already ignored by Git.

If startup fails, confirm Docker Compose v2 is available and no concurrent run is using the fixed project name. Audit failures should be resolved through an intentional dependency migration; the gate never runs `npm audit fix`. A release failure may also indicate that buildx/QEMU is not configured. Cleanup can be checked without touching other projects with Compose and Docker label filters for `industrial-ai-quality`.
