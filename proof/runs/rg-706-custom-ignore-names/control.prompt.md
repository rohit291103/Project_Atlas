You are working in the repository checked out in the current directory, at the commit before this feature was built. Implement the feature described below. Change only what the feature requires. When you are done, stop; your working tree diff is your answer.

# Support ignore files with custom names

This allows for application specific ignorefile names, e.g. using
`.fdignore` for `fd`.

- Moved the hardcoded `.rgignore` from the ignore crate to ripgrep

- `.ignore` is always respected and has the highest precedence

**ptzz:** See discussion in https://github.com/sharkdp/fd/issues/156, specifically https://github.com/sharkdp/fd/issues/156#issuecomment-347371863

**ptzz:** Should probably add tests that uses multiple ignore files and validates precedence.

**ptzz:** @BurntSushi Thanks for the comments!

> I think the way to solve your problem is to add an additional layer of ignore files that has higher precedence than .ignore but uses a custom (probably application specific) name.

Indeed I didn't read this carefully and assumed `.ignore` would have the highest precedence. I understand that just correcting the order won't solve the hierarchy issues that you talk about though.

I will try to find time to fix this properly.

**ptzz:** @BurntSushi I *think* it should be working as expected now. Also addressed your comments on naming and method signatures.

**ptzz:** @BurntSushi Tests have been added for 1+2 above. As for precedence tests, I added one that verifies that a custom ignore file have higher precedence than `.ignore`, and one that verifies that earlier custom ignore files have lower precedence than later.

Let me know if you want to see more extensive tests. I wasn’t sure if it would make sense to add precedence tests between e.g. custom ignore and `.gitignore`, as there already tests for `.ignore` over `.gitignore` and precedence should apply transitively.

As for 3, there are already tests that uses `.rgignore`, maybe that's sufficient? It's not hardcoded in the ignore crate anymore, but passed as a (hardcoded) parameter from ripgrep.


**ptzz:** @BurntSushi Do you have concerns about merging this and/or want more time for review? Let me know if there is anything I can address.

**ptzz:** Thanks, it was a great learning experience doing a bit of Rust!
