FROM python:3.12-slim AS backend

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/workspace/apps/api:/workspace/apps/api/scripts \
    RUFF_CACHE_DIR=/tmp/ruff-cache \
    MYPY_CACHE_DIR=/tmp/mypy-cache

WORKDIR /workspace

COPY apps/api/requirements.txt apps/api/requirements-dev.txt /tmp/requirements/
RUN python -m pip install --no-cache-dir --no-compile \
        -r /tmp/requirements/requirements-dev.txt \
        pip-audit==2.9.0 \
    && groupadd --gid 10002 quality \
    && useradd --create-home --uid 10002 --gid quality quality

COPY --chown=quality:quality . .

USER quality

ENTRYPOINT ["/workspace/quality-gate/run-quality-gate.sh"]
CMD ["help"]


FROM backend AS image-contracts

CMD ["image-contracts"]


FROM node:22-bookworm-slim AS portal

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1

WORKDIR /workspace

COPY package.json package-lock.json ./
COPY apps/admin-portal/package.json ./apps/admin-portal/package.json
RUN NODE_ENV=development npm ci --workspace apps/admin-portal --include-workspace-root --include=dev \
    && groupadd --gid 10002 quality \
    && useradd --create-home --uid 10002 --gid quality quality

COPY --chown=quality:quality apps/admin-portal ./apps/admin-portal
COPY --chown=quality:quality apps/api ./apps/api
COPY --chown=quality:quality quality-gate ./quality-gate
RUN chown quality:quality /workspace/apps/admin-portal

USER quality
WORKDIR /workspace/apps/admin-portal

ENTRYPOINT ["/workspace/quality-gate/run-quality-gate.sh"]
CMD ["help"]
