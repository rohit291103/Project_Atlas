You are working in the repository checked out in the current directory, at the commit before this feature was built. Implement the feature described below. Change only what the feature requires. When you are done, stop; your working tree diff is your answer.

# Support ignore files with custom names

*Assembled 2026-09-30 from confirmed claims only. 0 claim(s) still await review and are omitted, except where one contradicts a confirmed claim — those appear below as unresolved disagreements.*

**Readiness: 75/100** (3 of 4 checks pass)

- *Support ignore files with custom names*: No constraint confirmed — nothing says what this must not do.

## Support ignore files with custom names

### Goals

- Allow ignore files to use application-specific custom names (e.g. `.fdignore` for the `fd` tool) rather than a single hardcoded name.
  - > "This allows for application specific ignorefile names, e.g. using
`.fdignore` for `fd`." — [github_pr 706](https://github.com/BurntSushi/ripgrep/pull/706)

### Evidence

- Tests were added covering multiple ignore files and precedence ordering.
  - > "Tests have been added for 1+2 above." — [github_pr 706](https://github.com/BurntSushi/ripgrep/pull/706)

### Decisions

- Move the hardcoded `.rgignore` name out of the ignore crate and into ripgrep.
  - > "Moved the hardcoded `.rgignore` from the ignore crate to ripgrep" — [github_pr 706](https://github.com/BurntSushi/ripgrep/pull/706)

- Solve the problem by adding an additional layer of ignore files that has higher precedence than `.ignore` but uses a custom, application-specific name (BurntSushi's suggested approach).
  - > "I think the way to solve your problem is to add an additional layer of ignore files that has higher precedence than .ignore but uses a custom (probably application specific) name." — [github_pr 706](https://github.com/BurntSushi/ripgrep/pull/706)

### Architecture notes

- In the implemented behavior a custom ignore file has higher precedence than `.ignore`, and earlier custom ignore files have lower precedence than later ones.
  - > "I added one that verifies that a custom ignore file have higher precedence than `.ignore`, and one that verifies that earlier custom ignore files have lower precedence than later." — [github_pr 706](https://github.com/BurntSushi/ripgrep/pull/706)

- `.rgignore` is no longer hardcoded in the ignore crate; it is passed as a (hardcoded) parameter from ripgrep.
  - > "It's not hardcoded in the ignore crate anymore, but passed as a (hardcoded) parameter from ripgrep." — [github_pr 706](https://github.com/BurntSushi/ripgrep/pull/706)
