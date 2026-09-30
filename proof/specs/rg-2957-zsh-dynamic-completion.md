# feat(completion): support sourcing zsh completion dynamically

*Assembled 2026-09-30 from confirmed claims only. 0 claim(s) still await review and are omitted, except where one contradicts a confirmed claim — those appear below as unresolved disagreements.*

**Readiness: 75/100** (3 of 4 checks pass)

- *feat(completion): support sourcing zsh completion dynamically*: No constraint confirmed — nothing says what this must not do.

## feat(completion): support sourcing zsh completion dynamically

### Goals

- Allow zsh completions to be sourced dynamically, so `source <(rg --generate complete-zsh)` works without saving the script to a file first.
  - > "Now, you can dynamically source completions in zsh by running" — [github_pr 2957](https://github.com/BurntSushi/ripgrep/pull/2957)

### Problems

- Users cannot source ripgrep's zsh completions directly (e.g. `source <(rg --generate=complete-zsh)`); doing so fails with a zsh error, so the only workaround is writing the script to a file in fpath.
  - > "However, this doesn't work for ripgrep." — [github_issue 2956](https://github.com/BurntSushi/ripgrep/issues/2956)
  - > "_arguments:comparguments:327: can only be called from completion function" — [github_issue 2956](https://github.com/BurntSushi/ripgrep/issues/2956)

### Evidence

- The generate-and-source approach is slower (~4ms per invocation); a single lag is imperceptible but accumulates into something noticeable.
  - > "the text now makes it clear that the "generate and source" approach is slower" — [github_pr 2957](https://github.com/BurntSushi/ripgrep/pull/2957)
  - > "4ms might not seem like much, and indeed, I cannot perceive a 4ms lag, but if you accrue 10 of those kinds of things, it starts to pile up into something that is noticeable." — [github_pr 2957](https://github.com/BurntSushi/ripgrep/pull/2957)

### Decisions

- Document the dynamic generate-and-source method in the FAQ, with reworded wording adding a caveat emptor.
  - > "I've left it in the FAQ and fixed up the wording by adding an appropriate caveat emptor." — [github_pr 2957](https://github.com/BurntSushi/ripgrep/pull/2957)
