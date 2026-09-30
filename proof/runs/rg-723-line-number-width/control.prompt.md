You are working in the repository checked out in the current directory, at the commit before this feature was built. Implement the feature described below. Change only what the feature requires. When you are done, stop; your working tree diff is your answer.

# Add support for fixed width line number display (fixes #544)

As per the discussion on #544, this is my initial attempt at adding support for fixed width line numbers. Please review and let me know if things can be improved upon.

A few thoughts I had as I worked on this:

- Rust's `format!` macro currently has no way of providing a custom padding character as a parameter. You have to provide it directly in the format string itself. (As per [this](https://doc.rust-lang.org/std/fmt/#syntax), only the width can be provided as a parameter.)
- This meant that adding support for format strings as suggested in the issue discussion proved to be difficult. Right now, the argument only accepts a number. It seems that we'll have to write a custom code for left padding or rely on a library to achieve this. I'm open to suggestions on this one.
- Should we handle possible combinations of CLI args? In the long help message for `line-number-width`, I've mentioned that it has no effect if `--no-line-number` is enabled, which is very obvious. Should I handle any other cases specific to this newly introduced argument to ensure nothing breaks?

Thanks in advance!

**okdana:** In order to handle it as i suggested, i think you would want to have it check the argument string before conversion to `usize` and set a boolean in the `Args` struct to `arg.starts_with("0")`. Then you would pass that boolean to the printer and just have an `if` condition determine the format string to use

But it doesn't really matter either way obv. Would be a cute feature but certainly not important

Will add further comments on the diff

**balajisivaraman:** @BurntSushi, I understand your concern. When I was making the change, I thought we wanted it to be very general and support any padding character, which is why I looked into the `format!` macro.

However, if it is always going to be a choice between 0 or space, I could do what @okdana suggested. Then we can fail if the first character is anything other than a 0.

Let me know if this works for you and I can update the PR accordingly.

**BurntSushi:** I would suggest just starting with supporting spaces. We can add more support as needed, but we will need to return an error if the padding width starts with a zero. In fact, we should return an error if the width starts with anything other than 1-9, but that is already true in this PR since it would fail to parse as an integer.

**balajisivaraman:** @BurntSushi, Okay, I understand. Will update the PR accordingly. Thanks for the comments.

**BurntSushi:** @balajisivaraman This also needs to update the man page, which is done in this file: https://github.com/BurntSushi/ripgrep/blob/162e085b98f8f2c627a92402d2e38dda04fc3e48/doc/rg.1.md --- If you have pandoc on your system, then run the [`convert-to-man`](https://github.com/BurntSushi/ripgrep/blob/162e085b98f8f2c627a92402d2e38dda04fc3e48/doc/convert-to-man) script and commit the changes to `rg.1`. Thanks!

**balajisivaraman:** @BurntSushi, Oops! For some reason, I thought that was something automatically provided by `clap`. I've now updated the PR for the man pages as well as you suggested.

ETA: Do we need to add the issue number in the commit message, or is it enough to add it to the PR only? I see that it ends up creating a lot of noise in the actual issue thread. (Apologies if I did it wrong and it created noise in this issue's thread.)

**balajisivaraman:** Sorry, that is something I should've known better and added when I made that change itself. It is done now.

**BurntSushi:** @balajisivaraman Awesome! Thanks so much. Great work!

## Linked issue #544: Fixed width line numbers

It would be nice to be able to see the indentation level of searched text line up. One way to do this would be to have fixed width line numbers in search results. This could be accomplished through an option flag and left-padding with either spaces or zeroes when the flag is active.

As this is primarily of interest for matches within a file, only the matches within a file need be considered for how wide the line numbers should be. Alternatively, one could have a pre-determined width (i.e. 6) and overflow larger line numbers.

Implemented, this could look either like this:
```
$ rg needle --fixed-width-line-numbers
haystack.txt:
 12:    needle {
144:      needle {

silo.txt:
  16:  } needle {
 256:    } // needle 1
 512:    } // needle 2
1024:  } // needles

warehouse.txt:
   1234:  - needle ( 5 boxes )
1234567:  - needle ( 20 boxes )
```

Or like this:
```
$ rg needle --fixed-width-line-numbers
haystack.txt:
    12:    needle {
   144:      needle {

silo.txt:
    16:  } needle {
   256:    } // needle 1
   512:    } // needle 2
  1024:  } // needles

warehouse.txt:
  1234:  - needle (5 boxes)
1234567:  - needle (20 boxes)
```
