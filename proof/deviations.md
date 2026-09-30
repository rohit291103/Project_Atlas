# Deviations after the pre-registration was locked

The pre-registration (`preregistration.md`, locked 2026-09-30 18:10 UTC) is not edited after locking, because that would make every result unscoreable. Anything that changes after the lock is recorded here, with **what results existed when the change was made**.

## 1. The turn cap no longer crashes the run (2026-09-30)

- **What happened.** On the first agent session, the coding agent used all 40 turns (the pre-registered cap). The Agent SDK raises an error at that point rather than returning, so the whole run stopped before any diff was saved.
- **The change.** `run_agent` now treats reaching the cap as the end of the agent's budget: it captures whatever the agent changed, and records `hit_turn_cap` in `runs/<feature>/<condition>.meta.json`. Any other error still stops the run.
- **The cap itself is unchanged: 40 turns, as pre-registered.** A run that hits it is graded like any other. How many runs hit the cap in each condition goes in the write-up, because an agent that runs out of turns has not finished.
- **Harness hash:** `scripts/proof.py` went from `bf94aa89…8e96` (recorded in the pre-registration) to `8c66b65d…f9a`. The only code change is the cap handling and its metadata. A test was also added.
- **Results that existed at the time:** none. There were no diffs, packets or grades. Nothing had been seen that could steer this change.

## 2. Whitespace stripped from three control prompts (2026-09-30)

- **What happened.** The repository's pre-commit hooks (`trailing-whitespace` and `end-of-file-fixer`) ran over `proof/` while the prepared prompts were being committed. They removed trailing spaces from `runs/rg-111`, `rg-706` and `rg-723/control.prompt.md`, where the PR bodies carried them, and added final newlines to the curation files. The agent run then started from those files.
- **Effect.** The change is whitespace only (`git diff -w` shows nothing): no words were added, removed or reordered. It touched only control prompts, so it is technically an asymmetry between conditions. It is judged immaterial, but it's recorded rather than assumed.
- **Fix.** The two hooks now exclude `proof/` and `tests/evals/`, so recorded artifacts are never rewritten again.
- **Results that existed at the time:** none.

## 3. The coding agent could not edit files; its first two runs are discarded (2026-09-30)

- **What happened.** `rg-111` control and treatment both finished with **empty diffs** after using all 40 turns. Instrumenting a session showed every `Edit` returning `Tool permission request failed: Error: Stream closed`. The prompt stream ended after its one message, the SDK closed its input channel, and Claude Code's permission requests (which travel over that channel) could no longer be answered. The agent could read but never write, so it spent its turns retrying.
- **The change.** `held_stream` keeps the prompt stream open until the session's result arrives. It was verified live: an edit lands, a new file is captured in the diff, and a write outside the checkout is refused by the gate. A unit test pins the behaviour.
- **The discarded runs.** The two empty rg-111 diffs were deleted. They came from a harness that could not write, **in both conditions identically**, so they carry no information about either condition. All ten runs are repeated from scratch under the fixed harness. **No grading had happened, and no packet had been made.**
- **Harness hash:** `scripts/proof.py` is now `eb402d5afb10d30b596c7d8c0beaf47b74f9cb65cfdb2e394e4bfaf086aa34cd`. The cap (40 turns), the model and the prompts are unchanged.
