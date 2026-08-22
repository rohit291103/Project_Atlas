"""The API serving the built SPA from its own origin.

This is a *deployment* guarantee with a real failure mode behind it, which is
why it is tested rather than left to the first deploy to discover. The session
cookie is `SameSite=Lax`, so a frontend hosted on a different origin from this
API silently loses its session on every XHR — one origin is what makes the
production topology work at all (`docs/architecture/demo-deployment-v1.md`).

Two properties matter, and they pull against each other:

* every SPA route must survive a **reload** — a page served only by the dev
  server 404s in production the moment someone refreshes or shares a deep link;
* an unknown API path must still 404 **as JSON** — the obvious implementation
  (one catch-all returning `index.html`) answers `GET /products/nonsense` with
  200 and a page of HTML, so a typo in a client becomes a silent success.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from atlas.api.app import create_app

ROUTER_TS = Path(__file__).resolve().parents[1] / "frontend" / "src" / "router.ts"


@pytest.fixture
def built(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """A stand-in for `npm run build`'s output.

    A fixture rather than the real `frontend/dist`, which is gitignored and so
    absent in CI — the shape is what is under test, not the bundle.
    """
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><title>Atlas</title>")
    (tmp_path / "assets" / "index-abc123.js").write_text("console.log('atlas')")
    monkeypatch.setenv("ATLAS_STATIC_DIR", str(tmp_path))
    return TestClient(create_app())


def spa_paths() -> list[str]:
    """Every concrete path `frontend/src/router.ts::href` can return.

    Read out of the router itself so the two route tables cannot drift: adding a
    screen to the SPA without adding it to `SPA_ROUTES` means the new URL works
    in dev and 404s on reload in production, which is the kind of bug that is
    found by a stakeholder rather than by us.
    """
    source = ROUTER_TS.read_text()
    body = source[source.index("export function href") : source.index("export const PUBLIC_ROUTES")]
    returns = re.findall(r"return\s+[\"`]([^\"`]+)[\"`];", body)
    return [re.sub(r"\$\{[^}]+\}", "id0", path) for path in returns]


@pytest.mark.parametrize("path", spa_paths())
def test_every_spa_route_survives_a_reload(built: TestClient, path: str) -> None:
    response = built.get(path)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Atlas" in response.text


def test_the_router_actually_declared_some_routes() -> None:
    """Guards the parametrization above: a regex that silently matched nothing
    would turn the whole check into zero tests that all pass."""
    assert len(spa_paths()) >= 4
    assert "/" in spa_paths() and "/signin" in spa_paths()


def test_hashed_assets_are_served(built: TestClient) -> None:
    assert built.get("/assets/index-abc123.js").status_code == 200


def test_an_unknown_api_path_is_still_a_json_404(built: TestClient) -> None:
    """The property a catch-all would destroy."""
    response = built.get("/products/nonsense/deeper")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    json.loads(response.text)


def test_an_api_route_is_not_shadowed_by_the_page(built: TestClient) -> None:
    """`/session` is a real endpoint and must answer as one — 401 without a
    cookie, never a 200 page of HTML."""
    assert built.get("/session").status_code == 401


def test_the_api_still_runs_without_a_build(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A dev machine that has never run `npm run build`, and CI. Refusing to
    start here would break every backend-only workflow to serve a deployment
    concern."""
    monkeypatch.setenv("ATLAS_STATIC_DIR", str(tmp_path / "never-built"))
    client = TestClient(create_app())

    assert client.get("/session").status_code == 401
    assert client.get("/").status_code == 404
