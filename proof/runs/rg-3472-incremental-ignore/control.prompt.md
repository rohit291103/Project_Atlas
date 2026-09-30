You are working in the repository checked out in the current directory, at the commit before this feature was built. Implement the feature described below. Change only what the feature requires. When you are done, stop; your working tree diff is your answer.

# ignore: add incremental checking

This adds a new increment checker for ignore files, overrides and file
type selection. This effectively makes it possible to check individual
file paths as to whether they are ignored or not by any ignore file in
the directory tree (including parent gitignores). This is particularly
useful in the context of implementing a file watcher, where one wants to
make a decision about whether a newly added file should be included
*without* doing a full re-traversal of the directory tree.

This implementation reuses pretty much all of the existing gitignore
logic without making any changes to it.


**BurntSushi:** This PR is on crates.io in `ignore 0.4.30`.
