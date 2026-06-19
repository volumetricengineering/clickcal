# syntax=docker/dockerfile:1

# --- Build stage: install dependencies into a venv using uv ---------------
FROM ghcr.io/astral-sh/uv:python3.10-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# Install dependencies first (without the project) so this layer is cached
# across source changes. --frozen requires uv.lock to be up to date.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev

# Now copy the source and install the project itself.
COPY pyproject.toml uv.lock README.md ./
COPY clickcal ./clickcal
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# --- Runtime stage: minimal image with just the venv and app -------------
FROM python:3.10-slim-bookworm

# Run as a non-root user.
RUN useradd --create-home --uid 10001 appuser

WORKDIR /app

# Copy the prepared virtual environment and application code.
COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv
COPY --from=builder --chown=appuser:appuser /app/clickcal /app/clickcal

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    CLICKCAL_HOST=0.0.0.0 \
    CLICKCAL_PORT=8000

USER appuser
EXPOSE 8000

# Basic container health check against the app's health endpoint.
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request,os,sys; \
url=f'http://127.0.0.1:{os.environ.get(\"CLICKCAL_PORT\",\"8000\")}/healthz'; \
sys.exit(0 if urllib.request.urlopen(url, timeout=4).status==200 else 1)"

CMD ["clickcal"]
