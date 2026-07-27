# Phase 0 Validation Repo Selection

**Purpose:** Choose the public OSS repo + 3–5 historical PRs that Phase 0 validates extraction against — the standing golden set and the basis for the Phase 0 exit criteria ("usable, mostly-correct structured output on 3–5 real historical PRs," Roadmap / Phase0_Architecture.md §8). This resolves the open decision carried since scaffolding (Phase0_Architecture.md §9 Q1).

## Selection criteria

Tuned to what the extraction agent actually consumes, not just "a nice repo":

1. **Decision-rich PR prose** — descriptions/threads that state the *why* (goals), tradeoffs (decisions), limits (constraints), and things punted (open questions / rejected alternatives). Terse PRs give extraction nothing to find.
2. **Linked issues + referenced commits** — exercises the agent's `fetch_linked_issue` / `fetch_commit` / cross-reference-following, which is the core Phase 0 behavior being de-risked (vs. plain single-doc extraction).
3. **Multi-party review discussion** — Atlas assembles *a team's* scattered context; back-and-forth among contributor + maintainer + reviewers is more representative than a solo monologue.
4. **Comprehensible domain** — Phase 0 grading is manual/qualitative; the grader must judge "is this extracted requirement correct" without deep domain expertise.
5. **Modest diff size** — the agent has a ~8 tool-call budget; want rich *description*, scoped *diff*. Rules out sprawling 100+-comment mega-PRs.
6. **Public, read-only** — a fine-grained PAT scoped to one public repo (least-privilege, TRD §9).

## Decision

**Repo: [`BurntSushi/ripgrep`](https://github.com/BurntSushi/ripgrep).** Best fit on every axis: scoped single-feature diffs, a domain (a search-tool CLI) any engineer can grade, real contributor↔maintainer↔reviewer debate, and prose unusually dense in exactly our node types — BurntSushi documents *why* and *what-was-rejected* obsessively.

### Golden set (4 core, verified 2026-07-27)

| PR | Links | Why it's in the set |
|---|---|---|
| [#111](https://github.com/BurntSushi/ripgrep/pull/111) `--maxdepth` | `Closes #109` | PR body is *only* "Closes #109" → the agent **must** follow the link to #109 to recover the goal. The single best test of `fetch_linked_issue`. Comments carry decisions (depth semantics, `Option<usize>`, GNU-`find` alignment). |
| [#723](https://github.com/BurntSushi/ripgrep/pull/723) fixed-width line numbers | `#544` | Rich review debate → **rejected_alternative** (format-string args, custom padding), **constraint** (reject leading zeros), **open_question** (zero-padding explicitly punted: "I expect someone to request zero padding"). |
| [#706](https://github.com/BurntSushi/ripgrep/pull/706) custom ignore filenames | cross-repo `sharkdp/fd#156` | Tests external / cross-repo reference handling. **decision** (precedence hierarchy), **constraint** (`Arc<Vec<OsString>>` to avoid copies), API-naming decisions. |
| [#3472](https://github.com/BurntSushi/ripgrep/pull/3472) incremental ignore checking | (rationale in body) | Clear **goal + rationale** (enables a file watcher without full re-traversal); ~7 cross-platform edge cases → **constraints** (symlinks, case-insensitive FS, Windows hidden-attr, etc.). |

Together they cover the full node vocabulary (goal / requirement / decision / constraint / rejected_alternative / open_question) and the key edge types (a PR `implements` its linked issue; decisions `derive_from` evidence). #111's deliberately empty body is the sharpest agentic-behavior probe.

**Optional 5th (verify when building the golden set):** [#3420](https://github.com/BurntSushi/ripgrep/pull/3420) (`ignore: scope compiled parent matchers by root`) — a *bugfix*, which skews toward problem/evidence node types the four feature PRs under-represent. Add it if we want that diversity and it stays within budget.

## Alternatives considered

- **`pydantic/pydantic`** (stack-relevant, comprehensible): its decision-rich PRs (#2336 discriminated unions, #8237 deprecated fields, #6563 attribute docstrings) run 85–137 comments and large diffs — harder to grade cleanly and a real risk against the ~8 tool-call budget. Good *second* source if we later want variety.
- **`kubernetes/kubernetes`, `rust-lang/rust`**: gold-standard design rigor (KEPs/RFCs) but the domain demands expertise the manual grader may lack, and PRs/diffs are large. Deferred.
- **Single-maintainer caveat on ripgrep:** less "big team" than a large org repo, but the PR threads still have genuine multi-party decision-making (contributor + BurntSushi + reviewers), so criterion 3 is satisfied in practice.

## Next steps

1. Provision a fine-grained GitHub PAT scoped read-only to `BurntSushi/ripgrep` (public, so read-only is trivial) → `GITHUB_TOKEN` in `.env`.
2. Build `tests/evals/golden_set/pr-{111,723,706,3472}/` — recorded fetch (`raw.json`) + hand-authored `rubric.yaml` per PR (required node types + excerpt-source pairs). Recording the fetch also confirms each PR + its linked issues are reachable with the read-only token before any LLM spend.
3. With an `ANTHROPIC_API_KEY`, run `atlas ingest --repo BurntSushi/ripgrep --pr <n>` live across the set, then grade via the `writing-evals` / `extraction-quality-review` loop against the Phase 0 exit criteria.
