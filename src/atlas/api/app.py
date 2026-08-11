"""The ASGI application: router include, CORS, and nothing else.

Run it with `uv run uvicorn atlas.api.app:app --reload`. It needs
`SUPABASE_DB_URL`, `ATLAS_APP_PASSPHRASE` and `ATLAS_SESSION_SECRET` in the
environment (`.env` is loaded here, same as the CLI does) -- and deliberately no
GitHub token: the web-facing process cannot reach any source system, because it
has no credential for one.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from atlas.api.routes import router

__all__ = ["app", "create_app"]

#: The Vite dev server. In production the SPA is served from this same origin, so
#: no CORS entry is needed there -- and none is granted, since a wildcard origin
#: cannot be combined with credentialed requests anyway.
DEV_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")


def create_app() -> FastAPI:
    load_dotenv()
    app = FastAPI(
        title="Project Atlas API",
        version="0.1.0",
        summary="Read/write layer over the event log, serving the confirmation UI.",
    )
    if os.environ.get("ATLAS_DEV_CORS", "").lower() in {"1", "true", "yes"}:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(DEV_ORIGINS),
            # The session cookie has to ride along on cross-origin XHR in dev.
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.include_router(router)
    return app


app = create_app()
