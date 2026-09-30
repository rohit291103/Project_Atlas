You are working in the repository checked out in the current directory, at the commit before this feature was built. Implement the feature described below. Change only what the feature requires. When you are done, stop; your working tree diff is your answer.

# ignore: add incremental checking

*Assembled 2026-09-30 from confirmed claims only. 0 claim(s) still await review and are omitted, except where one contradicts a confirmed claim — those appear below as unresolved disagreements.*

**Readiness: 75/100** (3 of 4 checks pass)

- *ignore: add incremental checking*: No constraint confirmed — nothing says what this must not do.

## ignore: add incremental checking

### Goals

- Add an incremental checker for ignore files, overrides, and file type selection so individual file paths can be checked for ignore status.
  - > "This adds a new increment checker for ignore files, overrides and file
type selection. This effectively makes it possible to check individual
file paths as to whether they are ignored or not by any ignore file in
the directory tree (including parent gitignores)." — [github_pr 3472](https://github.com/BurntSushi/ripgrep/pull/3472)

### Problems

- When implementing a file watcher, deciding whether a newly added file should be included currently requires a full re-traversal of the directory tree.
  - > "particularly
useful in the context of implementing a file watcher, where one wants to
make a decision about whether a newly added file should be included
*without* doing a full re-traversal of the directory tree" — [github_pr 3472](https://github.com/BurntSushi/ripgrep/pull/3472)

### Requirements

- It must be possible to check whether an individual file path is ignored by any ignore file in the directory tree, including parent gitignores.
  - > "makes it possible to check individual
file paths as to whether they are ignored or not by any ignore file in
the directory tree (including parent gitignores)" — [github_pr 3472](https://github.com/BurntSushi/ripgrep/pull/3472)

### Architecture notes

- The implementation reuses essentially all of the existing gitignore logic without modifying it.
  - > "This implementation reuses pretty much all of the existing gitignore
logic without making any changes to it." — [github_pr 3472](https://github.com/BurntSushi/ripgrep/pull/3472)
