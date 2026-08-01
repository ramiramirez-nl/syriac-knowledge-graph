FROM python:3.12-slim

# curl is used by the container healthcheck; sqlite3 makes it possible to
# inspect the mounted database from inside the container.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app

# Copy dependency files first so the (slow) install layer is cached and only
# rebuilt when the dependency set actually changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

# /app/data is a mount point in production (fly.toml volume / compose volume).
RUN mkdir -p /app/data

ENV PORT=8080
EXPOSE 8080

# Fail fast if the app stops serving. /healthz is public and does not touch the
# database, so it stays cheap.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/healthz" || exit 1

# Shell form so ${PORT} is expanded: the platform decides the port, not the image.
CMD uv run uvicorn api.main:app --host 0.0.0.0 --port ${PORT}
