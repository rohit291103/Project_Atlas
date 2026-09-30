# Max depth option

*Assembled 2026-09-30 from confirmed claims only. 0 claim(s) still await review and are omitted, except where one contradicts a confirmed claim — those appear below as unresolved disagreements.*

**Readiness: 75/100** (3 of 4 checks pass)

- *Max depth option*: No constraint confirmed — nothing says what this must not do.

## Max depth option

### Goals

- Add a max depth command line option to ripgrep to limit directory traversal depth.
  - > "Max depth option" — [github_pr 111](https://github.com/BurntSushi/ripgrep/pull/111)

### Problems

- Skipping traversal of directories currently requires an .rgignore file, which is inconvenient to copy from repository to repository.
  - > "I know I can use an `.rgignore` file but it's not convenient to copy it from repository to repository." — [github_issue 109](https://github.com/BurntSushi/ripgrep/issues/109)

### Evidence

- GNU find defines maxdepth as descending at most the given non-negative number of levels, with -maxdepth 0 applying only to the starting-points themselves.
  - > "-maxdepth 0 means only apply the tests and actions to the starting-points themselves." — [github_pr 111](https://github.com/BurntSushi/ripgrep/pull/111)

### Requirements

- The change must include an integration test following the maintainer's established pattern for new command line flags.
  - > "Could you write an integration test please? It would be good to follow the pattern I've been using whenever I introduce new command line flags" — [github_pr 111](https://github.com/BurntSushi/ripgrep/pull/111)

- The test should verify that a deeper directory is ignored while search results are still returned from a shallower directory.
  - > "I think just updating the test to make sure it both ignores a deeper directory and gets search results from a shallower directory should be sufficient." — [github_pr 111](https://github.com/BurntSushi/ripgrep/pull/111)

### Decisions

- The max depth semantics should be consistent with GNU find.
  - > "Could you just make sure we are consistent with GNU find?" — [github_pr 111](https://github.com/BurntSushi/ripgrep/pull/111)

- The documentation should refer to "starting points" (as find does) rather than "current directory".
  - > "Probably saying "current directory" is wrong and we should say "starting points" like `find` does." — [github_pr 111](https://github.com/BurntSushi/ripgrep/pull/111)

### Architecture notes

- The max depth feature relies on the walkdir crate's notion of depth for directory traversal.
  - > "am I misunderstanding the depth used in `walkdir`?" — [github_pr 111](https://github.com/BurntSushi/ripgrep/pull/111)
