# Demo Deployment — one image, one origin

**Status:** built 2026-08-20, **not yet deployed to any host.** Everything below
runs locally; nothing here has been exercised on Fly or Render, and the first
deploy will find whatever this document got wrong.

**Why this exists:** the fastest way to show Atlas to someone is to run it
locally and share a screen — two commands, no hosting, no accounts. This
document is for the other case: a URL someone else can open.

---

## 1. The constraint that decides the topology

**The SPA must be served from the API's own origin.** This is not a packaging
preference and it is the one thing here that cannot be traded away.

The session is a signed, `httpOnly`, `SameSite=Lax` cookie
(`api/routes.py::sign_in`). A `Lax` cookie is **not sent on cross-site XHR**, so
the obvious split — SPA on Vercel, API on Fly — does not fail at deploy time
with a clear error. It fails later, in a browser, as a user who signed in
successfully and is then mysteriously signed out on every subsequent request.

The alternatives were considered and rejected:

- **`SameSite=None; Secure` plus a CORS allowlist.** Works, but it weakens the
  cookie's CSRF posture and adds an origin allowlist to keep in sync with
  whatever host the demo happens to live on this week — for a demo whose entire
  point is being easy to stand up.
- **A proxy in front of both.** Same origin, achieved by adding a component.
  Same result as serving the files from the API, with one more thing to deploy.

So: `create_app()` mounts the built bundle and serves `index.html` for the SPA's
own routes. `docker build` produces one image containing both halves.

## 2. What is served, and what deliberately is not

`SPA_ROUTES` in `api/app.py` lists the four patterns the SPA owns (`/`,
`/signin`, `/app`, `/p/…`), taken from `frontend/src/router.ts`. They are listed
**explicitly rather than served by a catch-all**, because a catch-all answers
`GET /products/nonsense` with `200` and a page of HTML — every mistyped API path
becomes a silent success. An unknown path under an API prefix still 404s as
JSON.

The cost is that the two route tables have to agree: a new screen in `router.ts`
needs a line in `SPA_ROUTES`, or its URL works in dev and 404s on reload in
production. `tests/test_static.py` reads `router.ts` and fails if they drift, so
this is enforced rather than remembered.

If the bundle is absent — a machine that has never run `npm run build`, or CI —
serving it is skipped and the API runs exactly as before. Backend-only workflows
are not broken to serve a deployment concern.

## 3. Deploying

Any host that runs a container works. The image needs no volume, no sidecar and
no second process.

```bash
docker build -t atlas .
docker run -p 8000:8000 --env-file .env atlas   # local smoke test
```

**Environment (four variables, and no more):**

| Variable | What it is |
|---|---|
| `SUPABASE_DB_URL` | The **`atlas_app`** role's URL — least privilege, RLS applies. Never the admin URL: migrations are run from a laptop, not by the web process. |
| `ATLAS_APP_PASSPHRASE` | The shared passphrase on the sign-in screen. |
| `ATLAS_SESSION_SECRET` | Signs the session cookie. Rotating it signs everyone out, which is the intended blast radius. |
| `ATLAS_SECRET_KEY` | The Fernet key for source credentials at rest. **Lose it and every stored connection is undecryptable** — there is no rotation path yet (roadmap-v2 Phase 4). |

`GITHUB_TOKEN` and the `JIRA_*` variables are deliberately **absent**: the web
process holds no source credential of its own. It only ever uses a credential a
person connected through the UI, decrypted per request.

**Fly.io:** `fly launch --no-deploy` (it will detect the Dockerfile), then
`fly secrets set` the four variables, then `fly deploy`. Keep it at one machine.

**Render:** a Web Service from this repo, environment "Docker", the four
variables as environment secrets, instance count 1.

Two settings are not optional on either:

- **One worker / one instance.** UI-triggered ingestion runs in-process via
  `BackgroundTasks` — no broker, an explicit CLAUDE.md Non-Goal. More than one
  instance is the moment that Non-Goal's exception fires and a queue is
  warranted.
- **`--proxy-headers`** (already in the image's `CMD`). The cookie's `Secure`
  flag is derived from `request.url.scheme`, which behind a platform load
  balancer reads `http` unless forwarded headers are trusted.

## 4. Migrations are not part of the deploy

The image carries `migrations/` and `alembic.ini` so a one-off container *can*
run `alembic upgrade head`, but the running service never does. Migrations need
the **owner** URL (`SUPABASE_DB_ADMIN_URL`), and the web process must not hold
owner credentials — that is the whole point of the `atlas_app` role
(`c3d8e1f60b21`). Run them from a laptop, as every migration to date has been:

```bash
set -a && source .env && set +a && uv run alembic upgrade head
```

The live database is at `b41c9d0e7f38` as of 2026-08-20.

### A new event type is a hard cutover, and the order is code first

Found the hard way on 2026-08-21: a long-running API process from before slice 3
started answering **500 on every read** once the first `product_described` event
was written. `replay()` raises on an event type it has no handler for — that is
deliberate and correct (silently skipping one would mean a projection quietly
missing state), but it means an **old reader cannot replay a log containing a
new event type at all**. Not "misses the new field" — cannot read anything.

So adding an `EventType` has three steps and they are ordered:

1. Apply the migration, so the database accepts the value.
2. Deploy the code that can *read* it, everywhere.
3. Only then write the first event of that type.

With one instance that is just "restart before seeding", and the restart is a
few seconds of downtime. It is worth knowing anyway, because it is the rule that
would make a rolling deploy of a new event type break the running one — which is
another reason the single-instance shape above is not merely a simplification.

## 5. Before showing it to anyone — the two real risks

Neither is a deployment problem, and both matter more than uptime.

**A visitor clicking Confirm writes a real, irreversible event.** There is no
sandbox mode. A confirmation is the product's unit of truth and the log only
moves forward, so a demo audience that starts ruling on claims is editing the
same workspace the Phase 1 exit measurement will read. Until slice 6 gives the
browser suite its own workspace, the same isolation is missing for demo
visitors. Either seat the demo in its own product, or hold the mouse yourself.

**Open the right product.** As of 2026-08-20 the workspace holds three:

- **Plausible Analytics** — the demo. Web analytics, which a PM reads without
  translation. Real public PRs from `plausible/analytics` on the GitHub side,
  and a Jira epic written for this demo (`scripts/seed_demo_jira.py`, project
  `PA`) on the other. Three of its acceptance criteria deliberately disagree
  with what the PRs decided, so the cross-source conflicts on screen are real
  disagreements between two real-looking sources.
- **ripgrep** — the Phase 0 validation fixture. Keep it; do not demo it. A PM
  watching a Rust CLI tool argue about `--maxdepth` traversal learns nothing
  about whether Atlas would help them, and it still carries duplicate feature
  scopes from before the re-run guard landed.
- **Slice 2B verification** — leftover plumbing check, not a demo.

The Jira half is authored, and the seed script says so in its own docstring:
nobody should present those tickets as Plausible's real backlog.
