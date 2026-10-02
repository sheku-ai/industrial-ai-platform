FROM python:3.12-slim AS dependencies

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

RUN python -m venv "$VIRTUAL_ENV"

COPY requirements.txt .
RUN pip install --no-cache-dir --no-compile -r requirements.txt

COPY requirements-intent-runtime.txt .
ARG INSTALL_INTENT_RUNTIME=false
RUN case "$INSTALL_INTENT_RUNTIME" in \
      true) pip install --no-cache-dir --no-compile -r requirements-intent-runtime.txt ;; \
      false) : ;; \
      *) echo "INSTALL_INTENT_RUNTIME must be true or false" >&2; exit 2 ;; \
    esac


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        fonts-dejavu-core \
        tesseract-ocr \
        tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 platform \
    && mkdir -p /app/runtime \
    && chown platform:platform /app/runtime

COPY --from=dependencies /opt/venv /opt/venv
COPY --chown=platform:platform . .

USER platform

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]


FROM runtime AS test

USER root

RUN pip install --no-cache-dir --no-compile -r requirements-dev.txt

COPY --chown=platform:platform --from=api_tests . /app/tests

USER platform


FROM runtime AS production
