# Confirmation UI — Flow Spec (v1)

**Status:** Proposal / first draft — not settled truth (root `CLAUDE.md`). This is the screen/flow spec for Phase 1 slice 1B, consuming `design-system-baseline-v1.md`. It resolves `Phase1_Architecture.md` §10 Q3 (confirmation UX) enough to build against; it does **not** pre-empt the `codebase-design` gate on the `api/` + frontend boundary (§5), which still runs before scaffolding.

**The bar this design is judged against:** a PM *outside the build team* can, *unassisted*, **review extracted elements and confirm/reject them in under 20 minutes** (Roadmap Phase 1 exit criterion). Every choice below is subordinate to that. Connecting a second source is part of the exit criterion but is largely slice 1C/1D surface; slice 1B proves the loop on **existing GitHub data**.

**Settled metaphor** (with the user, 2026-08-03): **document view as home + keyboard review mode layered on top.** Lead with comprehension (a first-time PM must *understand* the extracted picture before they trust it), then let them move fast. Not a pure card-queue — throughput is not the risk being retired; trust/usability is. Refined in the interactive mockup (2026-08-11, `docs/decisions/2026-08-11-confirmation-ui-design-direction.md`): distinct bordered cards; **only the focused card expands** (its source excerpt + actions), the rest stay compact; **reviewed items recede** into quiet dim one-line rows so the layout itself shows "to-do vs. done"; a top **"Review next" / auto-advance** flow guides the PM item to item.

**The cross-source model** (settled 2026-08-11, same decision doc — this is the reframe that keeps the UI aligned to Atlas's actual thesis):
- **The unit is the *feature*, not the source.** A feature scope is *assembled* from many tools (GitHub now; Jira Phase 1; Slack, Google Docs, email later). The screen is organized by feature and node type, **never split by source** (per-source tabs/panes just rebuild the silos Atlas removes).
- **Source is a property of each claim's provenance.** Every node carries a small **source badge** (`gh`/`sl`/`gd`/`@`/`you`); a node may carry **multiple `SourceRef`s** (the same fact corroborated across the PRD + a Slack thread) — already allowed by the schema.
- **Cross-source connections are the headline.** A requirement in the PRD conflicting with a decision in Slack is the thing *no single tool could surface* — the `conflicts_with` banner names **both sides' sources** and is the loudest element on screen. Surfaced, never auto-resolved (TRD §5.2).
- **Source-agnostic by construction.** The review UI is built so new connectors slot in without a redesign; connectors themselves are sequenced per the Roadmap and **not built ahead** (GitHub live, Jira next, Slack/Docs/email Phase 2–4).
- **No node-link graph canvas.** Interconnection is expressed as inline source badges + textual edges, not a graph view (over-scope + reintroduces overwhelm; explicit non-goal).

---

## 1. Information architecture

```
Workspace  (single, Phase 1 — DEFAULT_WORKSPACE_ID until 1D)
  └─ Feature scopes           ← left rail list, each = one ingested feature
       └─ Feature-scope review page   ← THE core screen (§3)
            └─ Node (card)     ← the unit of review (§4)
```
Phase 1 has one workspace (the nil sentinel until slice 1D brings real workspaces/RBAC). The left rail lists feature scopes; selecting one opens its review page. There is no global search, no cross-scope view, no spec view (all deferred).

---

## 2. Entry & auth (minimal, flagged)
App-level auth (`Phase1_Architecture.md` §10 Q2) is **still unsettled** and blocks *shipping* 1B, not designing it. This spec assumes: the PM lands authenticated, and the API derives `workspace_id` + `actor` from that session — **never** from a request body (carried constraint from the slice-1A decision doc). The login surface is speced once Q2 is settled. Source-OAuth (connecting GitHub/Jira) is a separate flow (§8), not app login.

---

## 3. The feature-scope review page (core screen)

A calm, top-to-bottom **document**: the whole extracted feature as one readable surface, grouped by node type in a why→what→how order, with unconfirmed items foregrounded and every action one keystroke away.

### 3.1 Layout
```
┌ left rail ┬──────────────── feature-scope review ─────────────────┐
│ Workspace │  ripgrep #111 · Add --pre preprocessor flag           │
│           │  [▓▓▓▓▓▓░░░░]  6 of 10 reviewed · 2 conflicts          │ ← progress + conflict count
│ Features  │ ─────────────────────────────────────────────────────│
│ › #111  ● │  GOALS · 1 · 0 to review                              │ ← section header
│   #723    │   ✓ Add a --pre flag to preprocess inputs   ●●● [Goal]│
│   #706 ⚠  │      ▸ "Closes #109"   ↗ source                       │
│   #3472   │                                                        │
│           │  PROBLEMS · 1 · 1 to review                           │
│           │   ○ ripgrep can't search non-text (pdf,gz)   ●●○ [Prob]│ ← focused (accent rule)
│           │      ▸ "…would be great to search inside…" ↗          │
│           │      [✓ confirm]  [✎ edit]  [✕ reject]                 │
│           │                                                        │
│           │  REQUIREMENTS · 4 · 2 to review                       │
│           │   ⚠ Must stream stdin, not buffer   ●●○ [Req]         │
│           │      ⚠ conflicts with Decision D1  ↗                   │
│           │   …                                                    │
└───────────┴────────────── j/k move · c/e/x act · o source · a add ┘
```

### 3.2 Node-type grouping & order (why → what → how)
Fixed section order, matching how a reader reconstructs a feature:
1. **Goals** — why it exists
2. **Problems** — what's wrong today
3. **Requirements** — what it must do
4. **Decisions** — what was chosen (and rejected alternatives)
5. **Constraints** — the boundaries
6. **Open Questions** — what's unresolved
7. **Architecture notes** — how it's shaped
8. **Evidence** — supporting excerpts

Empty types are omitted (no empty headers). Within a section, **unconfirmed sort to the top** so "what still needs you" is always the next thing your eye hits.

### 3.3 Progress & the 20-minute bar
Top-bar meter — "6 of 10 reviewed" — makes the exit criterion visible and gives a first-time PM a sense of finish-ability. Conflict count sits beside it (conflicts are the thing most worth not missing). When everything is reviewed, the meter resolves to a quiet "All 10 reviewed" done-state.

---

## 4. The node — states & interactions

Card anatomy is §6.1 of the design-system doc. Behavior:

### 4.1 Statuses (map exactly to the storage state machine)
- **unconfirmed** (`○`, neutral) — default. The only status that counts against the progress meter.
- **confirmed** (`✓`, green) — `c`. Card settles, drops out of "to review", stays visible.
- **edited** (`✎`, blue) — see §4.3. Carries a "view original" affordance (the `previous_content` link, TRD §6).
- **rejected** (`✕`, muted) — `x`. Collapses to a struck one-liner; kept in the log, filtered from any future spec. Reversible.

Because replay is **last-write-wins** (slice-1A decision doc), every action is trivially undoable — re-confirming a rejected node just appends another event. So actions are low-stakes by design, and the UI should feel that way (no scary "are you sure" on reject).

### 4.2 Provenance interaction (the trust moment)
- `▸`/click expands the excerpt inline (monospace well); `o` or `↗ source` opens the exact source anchor (PR/issue/comment deep-link) in a new tab.
- Expanding provenance is the single most important micro-interaction for trust — it must be instant and never navigate away unless the user explicitly opens the source.

### 4.3 Edit flow
- `e` / ✎ opens **inline** editing of the claim text (not a modal — stay in the document).
- Save → appends a `node_edited` event carrying `previous_content`; status → `edited`; a "view original" toggle appears.
- Type is editable too (a mis-typed Goal→Requirement is a common correction); a changed type re-sorts the card into its new section on save.
- Editing never destroys provenance — the original SourceRef excerpt is a snapshot and stays put.

### 4.4 Add a node (manual)
- `a` opens an inline "add" composer in the current section.
- It asks for a **claim and a type — not a citation.** Manual nodes use `human_assertion` provenance: the evidence is the PM who typed it, recorded automatically (`docs/decisions/2026-08-03-manual-node-provenance.md`). The composer must *not* ask the user to paste a source URL — that was the whole point of settling manual-node provenance.
- Result: `node_created`, `created_by = user`, `status = confirmed`, no confidence pip (`—`). Reuses the `add_node` write path.

### 4.5 Conflict presentation
- A node in a `conflicts_with` edge shows the amber banner (§6.6) inline, linking to its counterpart; the counterpart shows the reciprocal.
- Conflicts are **surfaced, never auto-resolved** (TRD §5.2). Resolution is the human's job: confirm one, reject/edit the other, or leave both flagged. The UI takes no position.
- Conflicts also count in the top-bar summary so they can't be scrolled past unseen.

---

## 5. Keyboard review mode
Layered on the document, not a separate screen:
| Key | Action |
|---|---|
| `j` / `k` | Next / previous node (focus ring moves; page auto-scrolls) |
| `c` | Confirm focused |
| `e` | Edit focused (inline) |
| `x` | Reject focused |
| `a` | Add node in current section |
| `o` | Open focused node's source |
| `Space` | Expand/collapse provenance |
| `u` | Undo last action (re-focuses the affected node) |
| `Tab` | (v1.x) jump to next *unconfirmed* only — blast mode |

Mouse and keyboard are fully equivalent; nothing is keyboard-only or mouse-only.

---

## 6. States: loading / empty / error
- **Loading** a scope: skeleton cards (never a blank screen), grouped shells so structure is legible before content lands.
- **Empty scope** (extraction produced nothing): honest empty state — "No elements extracted for this feature yet" + a route to re-ingest (CLI/engineer path in Phase 1), not a dead end.
- **API/replay error:** a non-destructive banner ("Couldn't load — retry"); never silently show stale state as current.

---

## 7. Mapping to the exit criterion
| Exit-criterion demand | How this design meets it |
|---|---|
| *Non-engineer, unassisted* | Document reads like a brief; no CLI, no jargon; provenance one click; actions labeled + hinted |
| *Review extracted elements* | §3 grouped why→what→how; unconfirmed foregrounded; provenance inline |
| *Confirm/reject* | §4/§5 one-key actions, reversible (low-stakes) |
| *Under 20 minutes* | Progress meter (§3.3), keyboard flow (§5), unconfirmed-first sort, calm single-scan layout |
| *Connect two sources* | §8 — mostly slice 1C/1D; 1B proves the loop on existing GitHub data |

---

## 8. Connect-sources surface (slice 1C/1D — speced thin here)
Not built in 1B, but designed for so the IA doesn't have to change later:
- A "Sources" area where the PM connects GitHub / Jira and **scopes** each to specific repos / epics / labels — a least-privilege *trust moment*, designed as a deliberate, legible step (mirrors source permissions, TRD §9 / Philosophy §6).
- Per-page (Notion) granularity and a fuller admin allow-list are Phase 2 / Phase 4 (`docs/research/2026-07-28-competitive-linear-and-ui-direction-v1.md` Part 3). Phase 1 is "connect two, scope each," not a marketplace.

---

## 9. Open questions this spec leaves for the build
1. **App auth entry** (`Phase1_Architecture.md` §10 Q2) — login surface unspeced until Q2 settles; blocks ship, not design.
2. **`codebase-design` gate** — the `api/`+frontend boundary (§5) runs *before* any of this is scaffolded; this spec is an input to that pass, not a bypass of it.
3. **Feature-scope list at scale** — Phase 1 has few scopes; sorting/search on the left rail is deferred until there are enough to need it.
4. **Edit conflict / concurrency** — single-PM Phase 1 assumes no simultaneous editors; multi-user contention is a Phase 4 (RBAC) concern.
5. **⌘K command palette** — fast-follow (v1.x), not v1.0-blocking.
