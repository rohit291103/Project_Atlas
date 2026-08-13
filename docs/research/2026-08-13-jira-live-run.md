# Jira, live for the first time — two defects, then the cross-source thesis working

**Date:** 2026-08-13
**Covers:** the first run of the Jira connector and Jira extraction against a real Atlassian Cloud site, and the first cross-source feature scope in the live database. Run log, not a decision doc.

## Setup

Site: a personal Atlassian Cloud project (`SCRUM`, "My PM Team"). Its five existing issues were Atlassian's onboarding template — no relation to any feature under review — so a **seed fixture** was created instead: an epic (`SCRUM-6`) and four tasks giving a PM-side account of the same feature as ripgrep PR #111, which was already in the live database as feature scope `Max depth option`.

The seed was written by a scratchpad script talking to the Jira REST API directly, **not** through `ingestion/jira.py`. Atlas is read-only into every source system in every scoped phase (Engineering Philosophy #1); a fixture generator must not become the exception that puts a write path in the module.

One of the four tasks (`SCRUM-8`) was written to **genuinely contradict** what the PR concluded — the PR requires GNU-find-consistent semantics measured from the search starting points, the ticket decides on the current working directory and says so explicitly. A planted conflict that isn't a real disagreement would only have tested the renderer.

## Defect 1 — search returned issues with no fields (Critical)

`atlas ingest-jira --epic SCRUM-6` failed with `Jira API 405: Method Not Allowed`. The 405 was a symptom two steps downstream of the actual bug.

`GET /rest/api/3/search/jql` returns **only issue ids** unless `fields` is passed by name. Not an error — a 200 with `{"issues":[{"id":"10009"}, ...]}`. The predecessor endpoint (`/rest/api/3/search`) returned a default field set, which is why the parameter looks redundant and is not.

Those field-less objects parsed cleanly into `JiraIssue`s with **empty key, empty summary, and a provenance URL of `https://<site>/browse/`** — a link that resolves to a page having nothing to do with the claim. `resolve_jira_keys` then returned `["", "", "", ""]`, and `GET /rest/api/3/issue/` (no key) is what actually produced the 405.

Had the epic been ingested one issue at a time via `--issue`, this would never have surfaced; had the 405 not happened, **four nodes would have been stored with plausible-looking provenance pointing at the wrong page.** That is the exact failure mode this product exists to prevent, and no fixture-based test could have caught it, because the fixtures were recorded from the endpoint's documented shape.

**Fixed:** `_SEARCH_FIELDS` is sent explicitly, listing exactly the fields `_Parser.issue` reads. Regression test asserts the parameter is present.

## Defect 2 — a blank key was not treated as an error

The parser accepted `key=""` and built a URL from it. Provenance that points at the wrong page is worse than provenance that is missing, because nothing downstream can tell the difference — the reviewer sees a plausible link, clicks it, and lands somewhere unrelated.

**Fixed:** `_Parser.issue` raises on a missing key. Defect 1 was one cause; the guard means the next cause, whatever it is, fails loudly at ingestion instead of silently at review time.

## The run

`atlas ingest-jira --epic SCRUM-6 --limit 10 --feature-scope <Max depth option>`

| Issue | Nodes | Edges | Cross-source |
|---|---|---|---|
| SCRUM-7 | 3 | 2 | 0 |
| SCRUM-8 | 5 | 8 | **5** |
| SCRUM-9 | 3 | 1 | 0 |
| SCRUM-10 | 6 | 5 | 1 |

The scope now holds **27 nodes — 8 from GitHub, 17 from Jira** — and every Jira excerpt was verified verbatim against the ticket it came from, with `/browse/<KEY>` provenance URLs.

**All five cross-source conflicts are real disagreements**, at confidence 0.9, and the agent found them by reasoning across sources rather than by matching text:

- Jira's "counts from the current working directory" ↔ the PR's "must be consistent with GNU find"
- Jira's "explicitly not matching GNU find" ↔ the same PR requirement
- Jira's CWD decision ↔ the PR's "documentation should say *starting points*, not *current directory*"
- Jira's "help text must say current directory throughout" ↔ that same documentation requirement
- Jira's "`--maxdepth 0` must still return matches inside the current directory" ↔ the PR's GNU-find evidence that `-maxdepth 0` applies only to the starting points themselves

The last one is the interesting result: it required connecting a product decision to a piece of evidence quoted from a man page in a code review, across two tools, and getting the direction of the contradiction right.

It also flagged one *same-source* conflict inside the Jira set (SCRUM-10's "differing from find makes `--mindepth` harder to explain" against SCRUM-8's "explicitly not matching find"), which is correct and worth noting: conflict detection is not restricted to cross-source pairs, it just labels which ones cross.

## Rendered

The review page shows "Assembled from `gh BurntSushi/ripgrep#111` `jr SCRUM-7` `jr SCRUM-8` `jr SCRUM-9` `jr SCRUM-10`", 27 cards, "8 conflicts" in the header, and 5 conflict banners naming Jira as the other side. No console errors. The GitHub requirement card carries both contradicting Jira decisions above its own excerpt — one card containing the thing neither tool could have shown alone.

## What this does and does not settle

- **Settled:** the Jira connector works against a live site, ADF flattening produces verbatim excerpts from real rich text, cross-source conflict detection works on real data, and the UI renders it.
- **Not settled:** extraction *quality* on Jira has no golden set and no rubric — this is one run on four tickets that were written to be extractable. Volume (17 nodes from 4 short tickets) is higher per word than the GitHub set; whether that is richness or noise is a judgement nobody has made against a rubric.
- **Note for the smoke suite:** `frontend/tests/ui-smoke.spec.ts` is written against the seeded local database (actors `Priya (PM)` / `Sam`, two sources). It does not pass against the live database, which has different actors and five source badges. Run it against its own seed.
