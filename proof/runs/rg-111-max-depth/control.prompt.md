You are working in the repository checked out in the current directory, at the commit before this feature was built. Implement the feature described below. Change only what the feature requires. When you are done, stop; your working tree diff is your answer.

# Max depth option

Closes #109


**gsquire:** I'm not sure of how to write a unit test because I think I would just be testing `walkdir` if I did :)

Let me know if you are more clever than me in this regard.


**BurntSushi:** @gsquire Could you write an integration test please? It would be good to follow the pattern I've been using whenever I introduce new command line flags: https://github.com/BurntSushi/ripgrep/blob/master/tests/tests.rs#L781-L820

Other than that and a few nits, this looks good, thanks!


**gsquire:** I rebased onto master and squashed. Is that the style of integration test you expected?


**BurntSushi:** @gsquire That's perfect! I had one last suggestion and then this is ready to go. Thanks so much!


**gsquire:** @BurntSushi Doing this causes the test to fail:

``` rust
wd.create_dir("one");
wd.create("one/foo", "far");
wd.create_dir("one/too");
wd.create("one/too/many", "far");

cmd.arg("--maxdepth").arg("1");

let lines: String = wd.stdout(&mut cmd);
let expected = path("one/pass:far\n");

assert_eq!(lines, expected);
```

But changing the depth to 2 passes...am I misunderstanding the depth used in `walkdir`?


**BurntSushi:** I goofed. Looks like your initial implementation is correct. I was off by
one. Could you just make sure we are consistent with GNU find? The docs
will need to be updated too. Sorry for short response. On mobile.

On Sep 27, 2016 2:40 PM, "Garrett Squire" notifications@github.com wrote:

> @BurntSushi https://github.com/BurntSushi Doing this causes the test to
> fail:
>
> wd.create_dir("one");
> wd.create("one/foo", "far");
> wd.create_dir("one/too");
> wd.create("one/too/many", "far");
>
> cmd.arg("--maxdepth").arg("1");
> let lines: String = wd.stdout(&mut cmd);let expected = path("one/pass:far\n");
>
> assert_eq!(lines, expected);
>
> But changing the depth to 2 passes...am I misunderstanding the depth used
> in walkdir?
>
> —
> You are receiving this because you were mentioned.
> Reply to this email directly, view it on GitHub
> https://github.com/BurntSushi/ripgrep/pull/111#issuecomment-249957714,
> or mute the thread
> https://github.com/notifications/unsubscribe-auth/AAb34tN10dEsKkF0JR2Cd86vipvZiHLBks5quWMCgaJpZM4KHO4u
> .


**gsquire:** It's okay, just wanted to verify.

Quoting from the [GNU find man page](http://man7.org/linux/man-pages/man1/find.1.html):

> Descend at most levels (a non-negative integer) levels of directories below the starting-points.
> -maxdepth 0 means only apply the tests and actions to the starting-points themselves.

So no need to update anything? I have to say, I thought having max depth of one and having a file in a directory below `.` would be found. This is why I asked you to confirm. No rush on this, I want to make sure I understand it correctly is all.


**BurntSushi:** @gsquire Ah OK. Looks good. I think just updating the test to make sure it both ignores a deeper directory and gets search results from a shallower directory should be sufficient. Also, I think the docs need to be updated. Probably saying "current directory" is wrong and we should say "starting points" like `find` does. Thanks for sticking with me!


**gsquire:** Sweet, I know the phrasing is important. I updated that and the test. Hope it's good to go!


**gsquire:** Looks like the build failure happened on master too...strange.


**BurntSushi:** Yup this looks great. The failure looks unrelated. Thanks so much for doing this and putting up with me! :-)


**gsquire:** I'm happy to be able to contribute, you're a Rust machine :)

Congrats on this project!


## Linked issue #109: Directory ignore command line

Do you think it would be valuable to add an option to skip traversing directories? I know I can use an `.rgignore` file but it's not convenient to copy it from repository to repository.

If so, I think I could try and implement it as well.
