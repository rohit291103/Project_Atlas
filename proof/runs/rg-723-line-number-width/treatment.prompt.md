You are working in the repository checked out in the current directory, at the commit before this feature was built. Implement the feature described below. Change only what the feature requires. When you are done, stop; your working tree diff is your answer.

# Add support for fixed width line number display (fixes #544)

*Assembled 2026-09-30 from confirmed claims only. 0 claim(s) still await review and are omitted, except where one contradicts a confirmed claim — those appear below as unresolved disagreements.*

**Readiness: 100/100** (4 of 4 checks pass)

## Add support for fixed width line number display (fixes #544)

### Goals

- Add support for fixed width line number display in ripgrep (addresses issue #544).
  - > "Add support for fixed width line number display (fixes #544)" — [github_pr 723](https://github.com/BurntSushi/ripgrep/pull/723)

### Requirements

- The tool must return an error if the padding width starts with a zero.
  - > "we will need to return an error if the padding width starts with a zero" — [github_pr 723](https://github.com/BurntSushi/ripgrep/pull/723)

- The width should error if it starts with anything other than 1-9; this already holds in the PR because such input fails to parse as an integer.
  - > "we should return an error if the width starts with anything other than 1-9, but that is already true in this PR since it would fail to parse as an integer." — [github_pr 723](https://github.com/BurntSushi/ripgrep/pull/723)

- The change must also update the man page (doc/rg.1.md), regenerating rg.1 via the convert-to-man script.
  - > "This also needs to update the man page, which is done in this file" — [github_pr 723](https://github.com/BurntSushi/ripgrep/pull/723)

### Constraints

- Rust's format! macro cannot take a custom padding character as a parameter; only the width can be a parameter, so the padding character must be hard-coded in the format string.
  - > "Rust's `format!` macro currently has no way of providing a custom padding character as a parameter. You have to provide it directly in the format string itself." — [github_pr 723](https://github.com/BurntSushi/ripgrep/pull/723)

### Decisions

- Start by supporting only space padding, adding more padding support later as needed.
  - > "I would suggest just starting with supporting spaces. We can add more support as needed" — [github_pr 723](https://github.com/BurntSushi/ripgrep/pull/723)

### Architecture notes

- In the current PR implementation, the line-number-width argument only accepts a number.
  - > "Right now, the argument only accepts a number." — [github_pr 723](https://github.com/BurntSushi/ripgrep/pull/723)

- The line-number-width option has no effect if --no-line-number is enabled.
  - > "it has no effect if `--no-line-number` is enabled" — [github_pr 723](https://github.com/BurntSushi/ripgrep/pull/723)

### Rejected alternatives

- Supporting any arbitrary padding character (via the format! macro), which was the original general approach explored.
  - > "I thought we wanted it to be very general and support any padding character, which is why I looked into the `format!` macro." — [github_pr 723](https://github.com/BurntSushi/ripgrep/pull/723)
