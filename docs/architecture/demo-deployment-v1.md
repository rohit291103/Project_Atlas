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

### Render free tier — the chosen host, 2026-08-26

Cost was the deciding constraint, and the landscape has moved: **Fly.io has no
free tier for new accounts** (a 2-VM-hour / 7-day trial, then a card),
**Koyeb closed its free Starter** after being acquired, and Railway's "free" is
a $5 monthly credit. Render still has a real free tier that takes a Dockerfile
and no credit card.

`render.yaml` at the repo root is a Blueprint: one `web` service, `runtime:
docker`, `plan: free`, healthcheck on `/`, and the four variables declared with
`sync: false` so Render prompts for them rather than this file carrying them.

**Region is `singapore`, and that is not arbitrary.** Supabase is in
`aws-1-ap-northeast-2` (Seoul). This app replays the whole event log per
request, so every extra 100ms of database round-trip is paid several times on
one page load — Oregon would cross the Pacific twice for the same work.

1. **Push.** Render deploys from GitHub, so **the deploy is a `git push`** —
   anything uncommitted is not in it. The running site is `origin/main`, never
   the working tree. That is this host's one footgun.
2. **New → Blueprint**, point it at `rohit291103/Project_Atlas`. It reads
   `render.yaml`; there are no build settings to fill in.
3. **Paste the four variables** when prompted. `SUPABASE_DB_URL` is the
   **`atlas_app`** URL, never the admin one.
4. **Smoke-test the four things that actually break**, below.

#### The free tier's one real cost, and how to live with it

A free instance **spins down after 15 minutes without inbound traffic**, and the
next request wakes it in roughly 50 seconds. There is no setting that turns this
off; the paid Starter instance (~$7/mo) is the only fix.

It is survivable, but only if it is planned for:

- **Before a live demo, open the URL a minute early** and leave the tab up. A
  warm instance behaves normally.
- **The PM measurement is the case that actually hurts.** Someone opening a cold
  link, unassisted, waits 50 seconds at a blank page and reasonably concludes it
  is broken — and that measurement *is* the Phase 1 exit criterion. Warm it
  immediately before sending the link, or pay for the month it happens in.
- **Ingestion is safer than it looks.** A pull runs in-process for 4–7 minutes,
  which sounds like a spin-down risk, but the Sources screen is polling
  throughout, so the traffic that keeps the instance awake is the same traffic
  that shows the run's progress. It is only unattended runs that are exposed —
  and there are none.

#### Why not Cloud Run, which is also free

Cloud Run throttles CPU to near-zero once a response is sent. UI-triggered
ingestion runs *after* the response, in-process via `BackgroundTasks` (an
explicit CLAUDE.md Non-Goal, so there is no worker to move it to), and a 4–7
minute run would be starved or killed. `--no-cpu-throttling` fixes it and
changes the billing model, which spends the free tier. The same reasoning rules
out Vercel and Netlify functions, whose request timeouts are shorter than a
single ingestion.

**If sleeping becomes the problem**, the always-on free option is an **Oracle
Cloud Always Free** ARM VM — genuinely free, never sleeps — at the cost of
running the container yourself behind Caddy or nginx for TLS. TLS is not
optional there: the session cookie's `Secure` flag is derived from the request
scheme.

`railway.json` is also in the repo and is correct, if the paid path is ever
taken.

**Why the healthcheck is `/` and not a `/health` endpoint.** `/` serves the SPA
index, which proves two things at once: the process is up, *and* the bundle
actually shipped (a wrong `ATLAS_STATIC_DIR` fails it, which is what you want).
It deliberately does **not** touch the database. A healthcheck that probes
Postgres turns a Supabase blip into a container restart loop, which makes an
outage worse rather than shorter — and restarting this process cannot fix a
managed database anyway.

**One instance, always.** Free plans give one by construction, so on Render this
costs nothing to honour — but it is an architectural constraint rather than a
consequence of the plan, and it must survive any later upgrade. UI-triggered
ingestion runs in-process with no broker; a second instance is the moment
CLAUDE.md's Non-Goal fires.

**`PORT` needs no handling.** Render injects it and the image's `CMD` already
reads `${PORT}`.

### After the first deploy, check these four

Run against the generated domain. These are the failures that actually happen,
in the order they happen:

| Probe | Expect | A wrong answer means |
|---|---|---|
| `GET /` | `200 text/html` | The SPA bundle did not ship — check `ATLAS_STATIC_DIR` and that stage 1 of the build ran. |
| `GET /nonsense-api-path` | `404 application/json` | A catch-all crept in; every mistyped API path is now a silent 200. |
| `GET /products` | `401 application/json` | Not the auth wall — if this 500s, the database is unreachable (pooler URL, or the `atlas_app` password). |
| Sign in, then reload | Still signed in | The session cookie lost its `Secure` flag or its host. Confirm `--proxy-headers` survived and that the SPA and API are on one origin. |

**Any container host works** — the image needs no volume, sidecar or second
process. What a replacement must provide: one instance, a CPU that keeps running
between requests (see Cloud Run above), and HTTPS terminated in front of it.

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
