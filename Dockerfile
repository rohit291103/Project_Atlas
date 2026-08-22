# One image, one origin, one process.
#
# The SPA is built here and served by the API itself, which is a requirement
# rather than a packaging preference: the session cookie is `SameSite=Lax`, so a
# frontend on a different host from this API loses its session on every XHR.
# Full reasoning and the host-by-host steps: docs/architecture/demo-deployment-v1.md
#
# Deliberately *not* here: no task queue, no worker, no second process. UI-
# triggered ingestion runs in-process via FastAPI BackgroundTasks (an explicit
# CLAUDE.md Non-Goal), which is why `--workers 1` below is correct rather than
# conservative — a second worker would not break a run, but it is the point at
# which the Non-Goal's "the day there is more than one API worker" clause fires.

# --- 1. the SPA -----------------------------------------------------------------
FROM node:22-slim AS web
WORKDIR /web

# Lockfile first: dependencies change far less often than source, so this layer
# survives most rebuilds.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
# Same origin, so the client's fetch base is a bare path. `api.ts` reads
# `import.meta.env.VITE_API_BASE ?? "http://localhost:8000"` — an empty string is
# a *set* value, so the localhost dev default does not apply.
ENV VITE_API_BASE=""
# `npm run build` is `tsc --noEmit && vite build`, so a type error fails the
# image rather than shipping a bundle nobody type-checked.
RUN npm run build

# --- 2. the API -----------------------------------------------------------------
FROM python:3.12-slim
# Pinned to the version this repo's `uv.lock` was written with, so the image
# resolves exactly what a local `uv sync` does.
COPY --from=ghcr.io/astral-sh/uv:0.11.26 /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_FROZEN=1

# Dependencies before source, for the same layer-caching reason.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --no-dev --no-install-project

COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
RUN uv sync --no-dev

COPY --from=web /web/dist ./frontend/dist
ENV ATLAS_STATIC_DIR=/app/frontend/dist

# Runs as a non-root user: this process holds the database credential and the
# Fernet key, and there is no reason for it to own its own filesystem.
RUN useradd --create-home --uid 10001 atlas && chown -R atlas:atlas /app
USER atlas

# `--proxy-headers` is load-bearing, not hygiene. The session cookie's `secure`
# flag is set from `request.url.scheme` (api/routes.py), and behind a platform
# load balancer that reads `http` unless the forwarded headers are trusted — so
# without this the cookie ships over HTTPS without its `Secure` flag.
ENV PORT=8000
CMD ["sh", "-c", "uv run --no-dev uvicorn atlas.api.app:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*' --workers 1"]
