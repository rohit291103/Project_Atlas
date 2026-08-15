# Entry surface and Sources — page specs (v1)

**Date:** 2026-08-15
**Covers:** the two surfaces `docs/ux/` did not have — the public front door (`/`, `/signin`) and the connect-a-source flow (`/p/:product/sources`).
**Builds on:** `design-system-baseline-v1.md` (tokens, components), `confirmation-flow-spec-v1.md` (the review screen, unchanged by this).
**Built in:** slice 2B — `docs/decisions/2026-08-15-connections-and-ui-ingestion.md`.

---

## 1. Why these surfaces exist at all

The Phase 1 exit criterion is a PM, **unassisted**, connecting two sources and reviewing what comes out, in under twenty minutes. Two things stood in the way and neither was the review screen:

1. **There was no front door.** `/` was a login form with nothing behind it explaining what the thing was. A PM arriving cold was asked for a credential before being told what would be done with it.
2. **Connecting a source meant opening a terminal.** The product's target user is a person who does not have `uv` installed.

Everything below serves those two, and nothing else. No settings page, no member management, no billing — none of which Phase 1 needs.

---

## 2. Route map

| Route | Who sees it | What it is |
|---|---|---|
| `/` | anyone | The landing page. A signed-in visitor is forwarded to `/app`. |
| `/signin` | anyone | The entry surface. A signed-in visitor is forwarded to `/app`. |
| `/app` | members | Product list. |
| `/p/:product` | members | Product home. |
| `/p/:product/sources` | members | **New.** Connections and run history. |
| `/p/:product/f/:feature` | members | Review — the core screen. |
| `/p/:product/conflicts` | members | Conflicts across the product. |

**One rule, stated once:** a private route with no session redirects to `/signin`; a public route with a session redirects to `/app`. Both use `replace`, so the back button never walks into a redirect loop. The redirect waits for the session check to settle, so a returning reviewer holding a valid cookie is never bounced through a login form they already passed.

**`/` changed meaning.** It was the product list; it is now the landing page, and the product list moved to `/app`. This is the only existing address whose meaning moved, and a signed-in visitor never sees the difference.

---

## 3. The landing page

### 3.1 What it must not do

The temptation on a page like this is customer logos, invented metrics ("teams save 6 hours a week"), and testimonials. **None of it is permitted here**, for a reason specific to this product: Atlas's entire claim is that it never states anything it cannot show you the source for. A landing page that overstates is a promise the product breaks in the first minute, and it breaks the one promise the product is *about*.

So: no logo wall, no numbers nobody measured, no named customers. The persuasion is the mechanism.

### 3.2 Structure

1. **Nav** — wordmark, three section anchors, theme toggle, sign in. Sticky, translucent with a blur.
2. **Hero** — the problem in the user's own words ("Your team already decided this. It's just scattered across six tools."), a lede that describes the actual mechanism, two actions, and one line of restraint underneath: *read-only into every source*.
3. **Why-strip** — three numbered panels: agents are faster than context; the answer exists in six places; the work is gathering, not writing.
4. **How it works** — Connect / Extract / Confirm, one card each, each closing with the constraint that makes it trustworthy rather than another benefit ("Every pull is deliberate… Never a crawl." / "A claim with no source is structurally impossible." / "Nothing extracted counts as true until a person has said so.").
5. **The conflict demo** — the differentiator, shown rather than claimed. **It uses a real conflict Atlas found** between a GitHub review comment and a Jira ticket on the ripgrep `--pre` feature. Both sides, both verbatim quotes, on the product's own "paper" surface.
6. **What it will not do** — four constraints, stated as refusals.
7. **Closer** + minimal footer.

### 3.3 Visual rules

- **The app's own tokens, not a marketing palette.** The pitch and the product look like one piece of software, which is itself part of the argument.
- **Quoted source material keeps the warm `--paper` surface** it has in the review screen. Evidence reads as evidence in both places.
- `clamp()` and `max-width` everywhere rather than per-section breakpoints; the page reads on a phone with one set of rules.
- Anchors wearing `.action` need `text-decoration: none` — the class is worn by both `<button>` and `<a>`, and the UA underline was a real defect a browser found and typecheck did not.

---

## 4. The entry surface (`/signin`)

Split layout: the form on the left, three promises on the right.

**The name field comes first and says what it is for.** It becomes the `actor` on every event that person writes — it *is* the audit record, not a display preference. Someone typing "test" here has quietly broken the trail, and this is the only moment to prevent that. The helper text says so in those terms: *"Recorded on every decision you make, so anyone reading this feature later can see who confirmed what."*

**The right panel is not decoration.** Someone about to hand a tool their GitHub token is told what it will and will not do *before* they do it: it only ever reads; every claim quotes its source; nothing is true until you say so. Putting this in a settings page afterwards would be putting it where nobody reads it.

**Failure is specific.** "You are not a member of any workspace" is a different answer from "wrong passphrase", and the API distinguishes them; the form shows whichever it got, rather than a generic failure. The footer says so in advance, so a PM whose name is not yet seated knows what happened.

On narrow screens the promise panel drops and the form takes the full width.

---

## 5. Sources (`/p/:product/sources`)

### 5.1 The three questions this screen answers

*What is connected? What can I pull? What happened when I did?* — in that order, top to bottom. Nothing else is on it.

### 5.2 Connecting

- **Source first** (GitHub / Jira), because it changes what the rest of the form asks for. Jira asks for the site, the project key, **and the email the token belongs to** — Jira Cloud authenticates email + token, and asking for one without the other builds a connection that can only fail on its first run.
- **The credential field is a password field**, always. A token typed in the clear is a token in a screen recording.
- **The note under it says three things, at the moment the question is being asked:** it is stored encrypted; you will only ever see the last four characters again; a read-only token is enough, because Atlas never writes. It links straight to the page where the token is minted.
- **The button says "Connect and check access", and that is literally what happens.** The response reports what the credential reached — *"BurntSushi/ripgrep — Public repository · 176 open issues"*. Least privilege is otherwise a claim the product makes about itself; this is the source system's own answer. A credential that cannot read its own scope is refused **here**, while the PM is still looking at the form.

### 5.3 Connected sources

One card per connection: source and scope as the title; host, a masked hint (`••••1234`), and last-used underneath. **A stored secret is never rendered because no response carries one.**

**Revoke is two steps and says what it does** — "Delete this credential" / "Keep it". It is a real delete: the ciphertext stops existing. The event log keeps the record that it happened, which is the part that should be permanent.

### 5.4 Pulling context

- The target field's label, placeholder and hint all change with the kind chosen (`acme/web#42`, `SCRUM-6`, a label). The rules are stated, not implied: *every pull is deliberate — one pull request, one issue, one epic, one label. Atlas never crawls.*
- **"Add to" defaults to a new feature and can name an existing one.** The note explains why that matters in one sentence: it is what makes a feature cross-source, so a contradiction becomes a conflict you can see rather than two halves that never meet. This is the single highest-value control on the screen and it is one dropdown.
- Epic and label runs show the limit; single-target runs do not, because it would mean nothing.

### 5.5 Run history

Newest first. One row per run: target, state, when, who, and — for a successful run — how many artifacts and claims, plus a link straight into reviewing them.

**State is carried by colour *and* by a word.** Colour alone fails for anyone who cannot distinguish the two, and a run's outcome is exactly the kind of thing that must not depend on hue.

**Four states, and the fourth is the honest one:**

| State | Shown as |
|---|---|
| running | "Working…" — pulsing dot; polling runs *only* while something is running, so an idle screen makes no requests |
| succeeded | "Done" + counts + a link to review |
| failed | "Failed" + the reason, verbatim, in monospace |
| interrupted | **"Interrupted — the server restarted mid-run"** |

Ingestion runs in the API process, so a process that dies leaves a start event and no terminal event — indistinguishable from a slow run. Rather than spin forever, a run older than thirty minutes with no terminal event says what actually happened. Same instinct as making an unscoped query return zero rows rather than an error.

---

## 6. Deferred, and why

- **A cross-product home / ⌘K palette** — plan §9 slice 2C, "only if wanted". Nothing in the exit criterion needs either.
- **Member management** — the PM's name is seated by hand for the measurement; a UI for it is Phase 4's RBAC surface.
- **Brand (logo, custom accent, typographic wordmark)** — still the deferred `brandkit` pass. The current mark is the geometric glyph from the design baseline and the accent is `--accent`. Deliberately not invented ad hoc mid-slice.
- **A settings screen** — there is nothing to put in it that is not on the Sources page.
