# Recall engine for the trilium-llm-wiki plugin, run as a sidecar next to Trilium.
#
# Multi-stage: resolve dependencies into a venv with uv, fetch the pinned
# embedding model, then ship only the venv, the model and app/ on python-slim.

# ---- builder: create /app/.venv using uv ----
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
ENV UV_PYTHON_PREFERENCE=only-system \
    UV_PYTHON_DOWNLOADS=never
# git: mcp-login-oauth is pinned by git tag. Builder stage only; the runtime image doesn't get it.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# ---- model: the int8 ONNX model + SentencePiece tokenizer, checksum-verified ----
FROM debian:bookworm-slim AS model
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY scripts/fetch-model.sh /fetch-model.sh
RUN /fetch-model.sh /models/e5-small

# ---- runtime ----
FROM python:3.12-slim-bookworm
# curl is used by the container healthcheck.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --from=model /models /models
COPY app/*.py ./

ARG APP_VERSION=dev
# glibc keeps freed embedding buffers otherwise: these hold a full build at ~300 MB instead of ~400.
ENV PATH="/app/.venv/bin:$PATH" \
    APP_VERSION=$APP_VERSION \
    MALLOC_ARENA_MAX=2 \
    MALLOC_TRIM_THRESHOLD_=65536 \
    RECALL_MODEL_DIR=/models/e5-small \
    RECALL_DATA_DIR=/data

VOLUME /data
EXPOSE 8082
HEALTHCHECK --interval=60s --timeout=5s --start-period=120s --retries=3 \
  CMD curl -sf -o /dev/null http://localhost:8082/health || exit 1
CMD ["python", "server.py"]
