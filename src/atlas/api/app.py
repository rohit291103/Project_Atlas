"""The ASGI application: router include, CORS, the built SPA, and nothing else.

Run it with `uv run uvicorn atlas.api.app:app --reload`. It needs
`SUPABASE_DB_URL`, `ATLAS_APP_PASSPHRASE` and `ATLAS_SESSION_SECRET` in the
environment (`.env` is loaded here, same as the CLI does) -- and deliberately no
GitHub token: the web-facing process cannot reach any source system, because it
has no credential for one.

**Serving the SPA from this same origin is a deployment requirement, not a
convenience** (`docs/architecture/demo-deployment-v1.md`). The session cookie is
`SameSite=Lax`, so it is not sent on cross-site XHR: a frontend on one host
talking to this API on another does not fail loudly, it fails as a signed-in
user who is mysteriously signed out. One origin removes that class of bug
entirely, and it is also what makes CORS unnecessary in production -- a wildcard
origin cannot be combined with credentialed requests anyway.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from atlas.api.routes import router

__all__ = ["app", "create_app"]

#: The Vite dev server. In production the SPA is served from this same origin, so
#: no CORS entry is needed there -- and none is granted, since a wildcard origin
#: cannot be combined with credentialed requests anyway.
#:
#: Both 5173 and 5174 are listed because Vite silently falls back to the next
#: free port when 5173 is taken, and the resulting failure is a CORS error in the
#: browser console that looks nothing like "you are on the wrong port".
DEV_ORIGINS = tuple(
    f"http://{host}:{port}" for host in ("localhost", "127.0.0.1") for port in (5173, 5174)
)


#: Where `npm run build` puts the SPA, relative to the repo root. Overridden by
#: `ATLAS_STATIC_DIR` in the container, where the source tree is not the layout.
DEFAULT_STATIC_DIR = Path(__file__).resolve().parents[3] / "frontend" / "dist"

#: The SPA's own routes, from `frontend/src/router.ts`. Listed explicitly rather
#: than served by a catch-all, and that is the whole design of this bit: a
#: catch-all would answer `GET /products/nonsense` with 200 and a page of HTML,
#: turning every mistyped API path into a silent success. These four patterns
#: cannot collide with an API route -- the API owns `/session`, `/products`,
#: `/feature-scopes`, `/nodes`, `/connections`, `/runs` -- so an unknown path
#: under those still 404s as JSON, which is what an API should do.
#:
#: **The two route tables have to agree.** Adding a screen to `router.ts` means
#: adding it here, or the new URL 404s on reload while working fine in dev.
#: `tests/test_static.py` fails if this list stops covering `router.ts`'s.
SPA_ROUTES = ("/", "/signin", "/app", "/p/{rest:path}")


def _serve_spa(app: FastAPI, static_dir: Path) -> None:
    """Serve the built SPA from this origin, if it has been built.

    Absent (a dev machine that has never run `npm run build`, or the test suite)
    this is a no-op: the API still works, and the Vite dev server serves the SPA
    on its own port with `ATLAS_DEV_CORS=1`. Failing loudly here would break
    every backend-only workflow to protect a deployment concern.
    """
    index = static_dir / "index.html"
    if not index.is_file():
        return

    # Hashed filenames, so they are immutable: a year of caching is safe and the
    # index below is deliberately *not* in this mount, because it is the one file
    # that must never be served stale.
    app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

    for route in SPA_ROUTES:
        # Default-argument binding, not a closure over `index`: every route
        # would otherwise share the loop's last value if this list ever varied
        # per route.
        app.get(route, include_in_schema=False)(lambda index_file=index: FileResponse(index_file))


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
    # After the router, so an API path can never be shadowed by a page.
    _serve_spa(app, Path(os.environ.get("ATLAS_STATIC_DIR", DEFAULT_STATIC_DIR)))
    return app


app = create_app()
