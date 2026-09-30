You are working in the repository checked out in the current directory, at the commit before this feature was built. Implement the feature described below. Change only what the feature requires. When you are done, stop; your working tree diff is your answer.

# feat(completion): support sourcing zsh completion dynamically

Summary:
Previously, you needed to save the completion script to a file and then
source it.  Now, you can dynamically source completions in zsh by
running

```zsh
$ source <(rg --generate complete-zsh)
```

Test plan:
1. Run `source <(rg --generate complete-zsh)`
2. Run `rg --generate=complete-zs<TAB>`

Before this commit, you would get an error after step 1.
After this commit, it should work as expected.

Closes #2956


**BurntSushi:** I've left it in the FAQ and fixed up the wording by adding an appropriate caveat emptor. I guess since other projects have found it useful to suggest this method it's probably not too big of a deal for ripgrep to do it too. But the text now makes it clear that the "generate and source" approach is slower. 4ms might not seem like much, and indeed, I cannot perceive a 4ms lag, but if you accrue 10 of those kinds of things, it starts to pile up into something that is noticeable.

**vegerot:** @BurntSushi I'm using a self-built version now, but jooc when will the next release be so others can use it?

**BurntSushi:** I don't know, sorry. See: https://github.com/BurntSushi/ripgrep/blob/master/FAQ.md#when-is-the-next-release

## Linked issue #2956: Can't source zsh completions directly

#### Describe your feature request

The way I load many completions is by sourcing them in my `.zshrc`, for example

```zsh
  if type fzf > /dev/null; then
	  source <(fzf --zsh)
  fi

  if type gh > /dev/null; then
	source <(TCELL_MINIMIZE=1 gh completion -s zsh)
  fi

  if type fd > /dev/null; then
	  source <(fd --gen-completions)
  fi
```

However, this doesn't work for ripgrep.  If I run `rg --generate=complete-zsh`, I get

```zsh
$ source <(rg --generate=complete-zsh)

_arguments:comparguments:327: can only be called from completion function
```

As a workaround, I can put `rg --generate=complete-zsh > /somewhere/in/fpath/_rg` and it works, but I'm hoping to avoid that
