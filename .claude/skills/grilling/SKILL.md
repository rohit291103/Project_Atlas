---
name: grilling
description: Interview the user relentlessly, one question at a time, about a plan or design until shared understanding is reached. Use when the user wants to stress-test a plan before building, uses any "grill" trigger phrase, or when another skill (codebase-design, feature-discussion, domain-modeling) needs to walk a design tree with the user.
---

# grilling

Interview the user relentlessly about every aspect of the plan or design until you reach a shared understanding. Walk down each branch of the design tree, resolving dependencies between decisions one by one.

## Rules

1. **One question at a time.** Ask, wait for the answer, then ask the next. Asking multiple questions at once is bewildering and produces shallow answers.
2. **Always propose a recommended answer.** Don't ask an open-ended question with no point of view — give your best answer and ask the user to confirm, correct, or override it.
3. **Explore before asking.** If a question can be answered by reading the codebase, `/docs`, or `docs/tracker.md`, do that instead of asking the user to repeat what's already written down.
4. **Follow dependencies.** If answer A changes which question B even makes sense, re-derive B in light of A rather than asking a pre-planned list.
5. **Stop when the tree is resolved**, not after a fixed number of questions. If every branch has a decided answer (explicit or by your recommendation going unchallenged), summarize and stop.

## Output

End the session with a short summary of the decisions reached. If the decisions are non-trivial per CLAUDE.md's Documentation Rules, hand off to the `docs-sync` skill to file them — don't leave a grilling session undocumented.
