/* Real-browser smoke test for the confirmation UI.
 *
 * This suite exists because `tsc` and `vite build` both passed while three real
 * defects sat in the rendered page: a viewer was shown keyboard shortcuts that
 * did nothing, expanding a source excerpt printed it twice, and a reviewed card
 * kept a full-loud conflict banner so *done* work was the noisiest thing on
 * screen. None of those are type errors. They are only visible when something
 * renders the page and looks at it.
 *
 * Rewritten for the four-zone review screen. The assertions that carried over
 * are the ones about behaviour the specs promise; the ones about `.card` and
 * `.provenance__toggle` went with the card, since provenance is no longer a
 * disclosure inside it — it is a column that is always on screen, which is the
 * change those old assertions were compensating for.
 *
 * Requires the API running against a seeded database (see playwright.config.ts).
 */

import { expect, test } from "@playwright/test";

import { actors } from "./fixture";

/* The suite signs in as its own two actors, seated by
 * `scripts/seed_test_workspace.py` in a workspace that exists only for these
 * tests and is rebuilt before every run (see tests/global-setup.ts). They used
 * to default to a *guess* at the local seed's names, which is how the suite
 * ended up confirming real claims in the workspace the demo is given from.
 *
 * `ATLAS_TEST_EDITOR` / `ATLAS_TEST_VIEWER` still override, for a run against a
 * deployed environment seeded some other way. */
const EDITOR = actors.editor;
const VIEWER = actors.viewer;
const ADMIN = actors.admin;
const PASSPHRASE = process.env.ATLAS_APP_PASSPHRASE ?? "letmein";

type Page = import("@playwright/test").Page;

/* The guided tour opens on any browser that has not seen it — which is every
 * Playwright context, since each one starts with empty storage. It navigates to
 * the product chooser on its first step, so left alone it would break the
 * `signIn` helper for all 23 tests below and put an overlay over most of them.
 *
 * Marking it seen is the same move the suite already makes with the
 * `X-Atlas-Automated` header: a machine declaring what it is. Onboarding is for
 * people. The two tour tests opt back in by clearing the flag themselves — the
 * tour is a real behaviour and is tested as one rather than hidden.
 */
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => window.localStorage.setItem("atlas.tourSeen", "1"));
});

/** Undo the opt-out above, for the tests that are about the tour itself. */
async function wantTour(page: Page) {
  await page.addInitScript(() => window.localStorage.removeItem("atlas.tourSeen"));
}

/** Sign in and stop, without entering a product. */
async function signInOnly(page: Page, name: string) {
  // `/` is the marketing page as of slice 2B; the form lives at its own route.
  await page.goto("/signin");
  await page.getByLabel("Your name").fill(name);
  await page.getByLabel("Passphrase").fill(PASSPHRASE);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForSelector(".switcher__trigger");
}

/** Sign in and enter a product.
 *
 * A product is a context you are inside, and the rail scopes to it, so almost
 * every screen below only exists once one is chosen. Each Playwright test gets
 * a fresh browser context and therefore no remembered product, which means a
 * workspace with more than one product always lands on the chooser here — so
 * this picks the first one explicitly rather than relying on that memory.
 */
async function signIn(page: Page, name: string) {
  await signInOnly(page, name);
  if ((await page.locator(".rail__item").count()) === 0) {
    await page.locator(".switcher__trigger").click();
    await page.locator(".switcher__menu .switcher__item").first().click();
  }
  await page.waitForSelector(".rail__item");
}

/** Sign in and open the first feature in the rail. */
async function openFirstFeature(page: Page, name: string) {
  await signIn(page, name);
  await page.locator(".rail__item").first().click();
  await page.waitForSelector(".qitem");
}

test("the page renders without console errors once signed in", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await openFirstFeature(page, EDITOR);
  expect(errors).toEqual([]);
});

/* A product is a context, not a row in a list.
 *
 * A PM who owns Google Meet and Google Keep is doing two different jobs, with
 * different repos, different Jira sites and different teams. The rail used to
 * show every product's features in one flat column, which interleaved those
 * jobs permanently. These three assertions are the whole of that model: the
 * rail shows one product, the switcher names which, and the features on screen
 * are only that product's.
 */
test("the rail shows one product's features, not every product's", async ({ page }) => {
  await signInOnly(page, EDITOR);

  // Before a product is chosen there is no feature list to be confused by.
  await expect(page.locator(".rail__item")).toHaveCount(0);

  await page.locator(".switcher__trigger").click();
  const entries = page.locator(".switcher__menu .switcher__item");
  const chosen = await entries.first().locator(".switcher__item-name").innerText();
  await entries.first().click();

  await expect(page.locator(".switcher__name")).toHaveText(chosen);
  await expect(page.locator(".rail__item")).not.toHaveCount(0);

  // The product's own screens live above its features, Conflicts among them —
  // it was previously reachable only by typing the URL. Matched loosely because
  // Conflicts carries a live count badge inside the same element.
  //
  // Order: the two *reading* destinations first (what is mine to do, then what
  // this product is), then the loop the product runs — connect, then review.
  // About joined between Overview and Sources on 2026-08-21; the order is
  // asserted rather than the set, because it is a deliberate reading order and
  // not an accident of the order the screens were built in. Quality joined
  // last on 2026-09-28: it is about the tool rather than the product.
  await expect(page.locator(".rail__nav-item")).toHaveText([
    /^Overview$/,
    /^About$/,
    /^Sources$/,
    /^Conflicts\d*$/,
    /^Quality$/,
  ]);

  /* One section label in the rail, not three.
   *
   * Those three destinations used to sit under mono all-caps group headings —
   * "CONNECT" over `Sources`, "REVIEW" over `Conflicts` — and since every group
   * held exactly one item, the rail rendered as a single column of alternating
   * type sizes with no readable parent/child relationship in it at all. The loop
   * those headings named survives in the order asserted above and in the glyph on
   * each row; the only heading left is the one with a list under it. */
  await expect(page.locator(".rail__group-label")).toHaveText(["Features"]);
  // Each nav row carries its glyph, which is what now separates a destination
  // from a label. Without it we are back to a column of identical-looking text
  // rows. Counted against the rows themselves rather than a literal, so adding
  // a destination without a glyph fails here instead of silently passing.
  const navRows = await page.locator(".rail__nav-item").count();
  await expect(page.locator(".rail__nav-item .rail__nav-icon")).toHaveCount(navRows);
});

test("the rail filter narrows the feature list and ⌘K reaches it", async ({ page }) => {
  await signIn(page, EDITOR);
  await page.waitForSelector(".rail__item");
  const before = await page.locator(".rail__item").count();

  // The shortcut has to land on the input, not merely be swallowed — that is the
  // whole reason it is bound to something real instead of an unbuilt palette.
  await page.keyboard.press("ControlOrMeta+k");
  await expect(page.locator(".rail__search input")).toBeFocused();

  await page.keyboard.type("zzzqqq");
  await expect(page.locator(".rail__item")).toHaveCount(0);
  await expect(page.locator(".rail__hint")).toContainText("No feature matches");

  await page.keyboard.press("Escape");
  await expect(page.locator(".rail__item")).toHaveCount(before);
});

test("the product you left is the product you come back to", async ({ page }) => {
  await signIn(page, EDITOR);
  const first = await page.locator(".switcher__name").innerText();

  /* Signing out lands on the marketing page, not the form. Waiting for that
     landing is not politeness: `signOut` awaits its `DELETE /session` before it
     navigates, so calling `page.goto("/signin")` straight after the click can
     abort the request in flight. The cookie then survives, `/signin` redirects
     a still-valid session back into the app, and the test times out waiting for
     a form that will never render. Flaked exactly that way on 2026-08-25. */
  await page.getByText("Sign out").click();
  await page.waitForURL(/\/$/);
  await signInOnly(page, EDITOR);

  // No chooser this time: the remembered context reopens directly.
  await expect(page.locator(".switcher__name")).toHaveText(first);
  await expect(page.locator(".rail__item")).not.toHaveCount(0);
});

test('"All products" stays reachable, so the default never becomes a cage', async ({ page }) => {
  await signIn(page, EDITOR);
  await page.locator(".rail__foot").getByText("All products").click();

  await expect(page).toHaveURL(/\/app$/);
  await expect(page.locator(".rail__item")).toHaveCount(0);
});

/* The work-left counts, on all three surfaces they feed.
 *
 * These are one datum — `FeatureScopeRow.counts`, computed in
 * `storage/projections.py` — deliberately rendered in three places. The failure
 * mode being guarded is not "the number is missing" but "the numbers disagree",
 * which is what happens the moment any of them is derived locally instead.
 */
test("the rail, the nav and the dashboard all report the same work left", async ({ page }) => {
  await signIn(page, EDITOR);

  // Rail rows carry a count, not source badges: what a PM navigates on is how
  // much is left, not which tool fed it.
  const badges = page.locator(".rail__item .rail__badge");
  await expect(badges.first()).toBeVisible();

  /* Conflicts is counted as disagreements, so the nav badge and the dashboard's
     own figure must agree. This used to read the count out of the overview's
     one-line summary; that line is gone from the populated view, because the
     dashboard restated all four of its numbers directly underneath it. The
     assertion is the same one, pointed at the tile. */
  const navBadge = page
    .locator(".rail__nav-item", { hasText: "Conflicts" })
    .locator(".rail__badge");
  if (await navBadge.count()) {
    const navCount = Number((await navBadge.innerText()).trim());
    const tile = page.locator(".stat", { hasText: "Unresolved conflicts" }).locator(".stat__n");
    expect(Number((await tile.innerText()).trim())).toBe(navCount);
  }
});

test("the product home leads with what needs a ruling, conflicts first", async ({ page }) => {
  await signIn(page, EDITOR);

  const rows = page.locator(".work__row");
  await expect(rows.first()).toBeVisible();

  // A conflict is a decision nobody has made; a backlog is only work. Every
  // feature carrying a conflict sorts above every feature that doesn't.
  const withConflict = await page
    .locator(".work__list li")
    .evaluateAll((items) => items.map((li) => Boolean(li.querySelector(".work__conflicts"))));
  const lastConflict = withConflict.lastIndexOf(true);
  const firstClean = withConflict.indexOf(false);
  if (lastConflict >= 0 && firstClean >= 0) expect(lastConflict).toBeLessThan(firstClean);
});

test("the review footer and the rail agree on what a conflict is", async ({ page }) => {
  await openFirstFeature(page, EDITOR);

  const footer = page.locator(".queue__conflicts");
  if ((await footer.count()) === 0) return;

  // "8 claims in 6 conflicts" — the claim count and the disagreement count are
  // different numbers, and the footer used to show only the first while the
  // rail showed only the second.
  const text = await footer.innerText();
  const [, claims, pairs] = /(\d+)\s+claims?\s+in\s+(\d+)\s+conflicts?/.exec(text) ?? [];
  expect(claims, `footer read: ${text}`).toBeDefined();
  expect(Number(claims)).toBeGreaterThanOrEqual(Number(pairs));
});

test("opening a feature gives it a URL you can return to", async ({ page }) => {
  await openFirstFeature(page, EDITOR);

  // The defect this replaces: the selected feature was component state, so
  // refresh dropped you on whichever feature loaded first and nothing could be
  // linked to anyone.
  await expect(page).toHaveURL(/\/p\/[^/]+\/f\/[0-9a-f-]{36}$/);
  const url = page.url();
  const claim = await page.locator(".claim").innerText();

  await page.reload();
  await page.waitForSelector(".claim");
  expect(page.url()).toBe(url);
  await expect(page.locator(".claim")).toHaveText(claim);
});

test("the browser back button works", async ({ page }) => {
  await openFirstFeature(page, EDITOR);
  await page.goBack();
  await expect(page.locator(".rail__item")).not.toHaveCount(0);
});

test("only one claim is on the stage, and its source is always visible", async ({ page }) => {
  await openFirstFeature(page, EDITOR);

  // The load-bearing fix: the old build rendered provenance for every
  // *unreviewed* claim, so landing on a feature showed everything expanded at
  // once. Exactly one claim is staged now, and its excerpt is on screen without
  // anyone having to open anything.
  await expect(page.locator(".claim")).toHaveCount(1);
  await expect(page.locator(".ev .doc__excerpt").first()).toBeVisible();
});

test("the queue collapses nine node types into four groups", async ({ page }) => {
  await openFirstFeature(page, EDITOR);

  const labels = await page.locator(".qgroup").allInnerTexts();
  expect(labels.length).toBeLessThanOrEqual(4);
  for (const label of labels) {
    // `allInnerTexts` returns rendered text, so the CSS uppercase comes with it;
    // match case-insensitively rather than asserting the styling by accident.
    expect(label).toMatch(/why this exists|what it must do|how it was decided|unresolved/i);
  }
});

test("confirming advances to the next claim still needing a ruling", async ({ page }) => {
  await openFirstFeature(page, EDITOR);

  const staged = await page.locator(".claim").innerText();
  await page.getByRole("button", { name: /Confirm/ }).click();

  // Speced in flow spec §5 and never built before: without it the reviewer has
  // to hunt for the next item, which is most of the 20-minute budget.
  await expect(page.locator(".claim")).not.toHaveText(staged);
  await expect(page.locator(".qitem--confirmed")).not.toHaveCount(0);
});

test("a reviewed claim recedes in the queue but is still reachable", async ({ page }) => {
  await openFirstFeature(page, EDITOR);
  await page.getByRole("button", { name: /Confirm/ }).click();

  const reviewed = page.locator(".qitem--reviewed").first();
  await expect(reviewed).toBeVisible();
  await reviewed.click();
  await expect(page.locator(".status--confirmed")).not.toHaveCount(0);
});

test("a cross-source conflict names the other side's tool", async ({ page }) => {
  await signIn(page, EDITOR);
  // The cross-source feature is the one assembled from two tools.
  await page.locator(".rail__item").first().click();
  await page.waitForSelector(".qitem");

  const flagged = page.locator(".qitem__flag");
  if ((await flagged.count()) === 0) test.skip(true, "this feature has no conflicts");

  await flagged.first().click();

  /* The promise being guarded is unchanged — a disagreement must name the tools
     on each side, since "no single tool could have told you this" is the whole
     claim. What changed is the shape it is made in: a one-line banner became
     two cards side by side (`.versus`), so the assertion moved from the banner's
     prose to the source label on each side. A claim can disagree with several
     others, so the block names them all in one header rather than repeating
     itself per edge. */
  const versus = page.locator(".versus");
  await expect(versus).toHaveCount(1);
  await expect(versus.locator(".versus__side.is-this")).toHaveCount(1);

  const tools = await versus.locator(".versus__from").allInnerTexts();
  expect(tools.length).toBeGreaterThanOrEqual(2);
  expect(tools.every((tool) => /Jira|GitHub|a person/.test(tool))).toBe(true);
  // Cross-source is the case worth naming out loud, and the header says so.
  await expect(versus.locator(".versus__head")).toContainText(/disagree|contradict/);
});

test("the conflicts screen shows both sides of a disagreement together", async ({ page }) => {
  await openFirstFeature(page, EDITOR);

  const link = page.locator(".queue__conflicts");
  if ((await link.count()) === 0) test.skip(true, "no conflicts in this product");
  await link.click();

  await page.waitForSelector(".pair");
  // The point of the screen: two claims, side by side, one object. The old
  // build drew a banner on each endpoint and never put them on screen together.
  const pair = page.locator(".pair").first();
  await expect(pair.locator(".side")).toHaveCount(2);
  await expect(pair.locator(".side__ex")).toHaveCount(2);
});

test("a viewer is shown no write affordances at all", async ({ page }) => {
  test.skip(!VIEWER, "no viewer actor in this workspace (ATLAS_TEST_VIEWER is set to empty)");
  await openFirstFeature(page, VIEWER);

  await expect(page.locator(".actions")).toHaveCount(0);
  // Not just the buttons: advertising `c confirm` to a viewer teaches a shortcut
  // that silently does nothing.
  await expect(page.locator(".hints")).toContainText("read-only");
  await expect(page.locator(".hints")).not.toContainText("confirm");
});

test("the add composer never asks for a citation", async ({ page }) => {
  await openFirstFeature(page, EDITOR);
  await page.keyboard.press("a");
  await page.waitForSelector(".composer textarea");

  // PRD R10 + the manual-provenance decision: the evidence is the person who
  // typed it. Asking for a URL is how fabricated provenance gets in.
  await expect(page.locator(".composer")).toContainText("asserted by");
  await expect(page.locator(".composer")).not.toContainText(/url|https?:/i);
});

/* The type floor.
 *
 * Before 2026-08-16 the scale was 11/12.5/14/17/23, and 42 of the ~90
 * font-size declarations in the stylesheet ignored it entirely to hardcode
 * 10px or 10.5px. The densest, most-read screen in the product was therefore
 * rendered almost entirely between 10px and 12.5px, in a grey that failed
 * WCAG AA. It read as faint and unfinished regardless of the layout.
 *
 * 11px is reserved for mono all-caps labels, which read visually larger than
 * their nominal size because of the capitals and letter-spacing. Nothing may
 * go below it. This asserts against *computed* styles on the real review
 * screen, so a new component hardcoding `font-size: 10px` fails here rather
 * than shipping.
 */
test("no text on the review screen renders below the 11px floor", async ({ page }) => {
  await openFirstFeature(page, EDITOR);

  const tooSmall = await page.evaluate(() => {
    const offenders: { px: number; cls: string; text: string }[] = [];
    for (const el of document.querySelectorAll("*")) {
      // Only elements owning actual text — a wrapper's inherited size is its
      // children's problem, and counting it would report each string twice.
      const ownsText = [...el.childNodes].some(
        (n) => n.nodeType === Node.TEXT_NODE && n.textContent?.trim(),
      );
      if (!ownsText) continue;
      const px = parseFloat(getComputedStyle(el).fontSize);
      if (px < 11) {
        offenders.push({
          px,
          cls: el.className?.toString().slice(0, 40) ?? "",
          text: el.textContent?.trim().slice(0, 30) ?? "",
        });
      }
    }
    return offenders;
  });

  expect(tooSmall).toEqual([]);
});

/* --- the review screen's structure (2026-08-18 rebuild) --------------------
 *
 * Three assertions about shape rather than behaviour, each guarding a defect that
 * was visible in a screenshot and invisible to `tsc`, `vite build` and every test
 * above: three panes wearing three different header treatments, a claim marooned
 * above several hundred pixels of empty column, and widths nobody could change.
 */

test("every label on the review screen belongs to one type system", async ({ page }) => {
  await openFirstFeature(page, EDITOR);

  /* The defect: the queue's header rendered sans 13/550 in full-strength ink
     while the two beside it — at the same y, at the same level of the hierarchy —
     rendered 11px mono all-caps in the faintest grey on the palette. Three
     headings styled as though they came from three different applications.

     Every card label now resolves to one rule, so there is a single treatment to
     be consistent about instead of three to keep in sync by hand. Colour is
     deliberately excluded: the evidence card sits on the product's one warm
     surface and its label takes the paper family so it stays legible there. */
  const heads = await page.locator(".card__title").evaluateAll((els) =>
    els.map((el) => {
      const style = getComputedStyle(el);
      return [
        style.fontSize,
        style.fontWeight,
        style.letterSpacing,
        style.textTransform,
        style.fontFamily,
      ].join(" | ");
    }),
  );
  expect(heads.length).toBeGreaterThanOrEqual(2);
  expect([...new Set(heads)]).toHaveLength(1);

  // And exactly one sans heading on the screen: the feature's own name.
  await expect(page.locator(".rv__title")).toHaveCount(1);
});

test("the claim is set in the same weight system as everything around it", async ({ page }) => {
  await openFirstFeature(page, EDITOR);

  /* `.claim` was `font-weight: 450` — the only 450 in the stylesheet, next to 92
     uses of 500, 14 of 550, 17 of 600 and 4 of 400. At 24px that made the one
     piece of text the whole screen exists to show the *lightest* sans on it,
     which is why it read as a different typeface rather than as the hero. The
     size is what makes it the hero; the weight belongs to the system. */
  const weights = await page.evaluate(() => {
    const seen = new Set<string>();
    for (const el of document.querySelectorAll("*")) {
      const ownsText = [...el.childNodes].some(
        (n) => n.nodeType === Node.TEXT_NODE && n.textContent?.trim(),
      );
      if (!ownsText) continue;
      seen.add(getComputedStyle(el).fontWeight);
    }
    return [...seen].sort();
  });
  expect(weights).toEqual(["400", "500", "550", "600"]);

  // And light mode gets the subpixel renderer back. `-webkit-font-smoothing:
  // antialiased` was global, which on macOS strips about half a weight step off
  // dark-on-light text — the light theme rendered thin at every size.
  await page.getByRole("button", { name: /theme/i }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  expect(
    await page.evaluate(() => getComputedStyle(document.body).webkitFontSmoothing),
  ).toBe("auto");
});

test("the claim and its evidence are adjacent, and the rulings follow the claim", async ({
  page,
}) => {
  await openFirstFeature(page, EDITOR);
  await page.setViewportSize({ width: 1600, height: 900 });

  /* The trust argument of the whole product is that a claim and the literal words
     it came from can be compared. They used to be in two fixed panes with the
     action bar sticky-pinned to the viewport's bottom edge, which on a tall
     display left a few hundred pixels of nothing between a claim and the buttons
     that rule on it. Claim and evidence are grid siblings now, so on a wide
     workspace they sit abreast. */
  const claim = await page.locator(".card--claim").boundingBox();
  const evidence = await page.locator(".card--paper").boundingBox();
  expect(claim, "the claim card should be on screen").not.toBeNull();
  expect(evidence, "the evidence card should be on screen").not.toBeNull();
  // Abreast: the evidence card starts to the right of the claim card, not below.
  expect(evidence!.x).toBeGreaterThan(claim!.x + claim!.width - 1);

  // The rulings are inside the claim card, following its text — not floating at
  // the foot of the pane with a gradient over whatever they cover.
  const actions = await page.locator(".actions").boundingBox();
  expect(actions!.y).toBeGreaterThan(claim!.y);
  expect(actions!.y).toBeLessThan(claim!.y + claim!.height);
});

test("the claim list can be resized and got out of the way", async ({ page }) => {
  await openFirstFeature(page, EDITOR);
  const queue = page.locator(".rv__queue");
  const before = (await queue.boundingBox())!.width;

  /* Driven from the keyboard on purpose: this screen is keyboard-first (design
     baseline §1.4, §7), so a resizer only a mouse can reach is a control half
     this product's own reviewers cannot use. */
  await page.locator(".rv__grip").focus();
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  expect((await queue.boundingBox())!.width).toBeGreaterThan(before);

  // ...and the pane goes away entirely, which a hard-coded 300px column never
  // could. The claim stays, because hiding the list is not leaving the screen.
  await page.keyboard.press("[");
  await expect(page.locator(".rv__queue")).toHaveCount(0);
  await expect(page.locator(".claim")).toBeVisible();

  // The width survives a reload — a width you re-drag on every navigation is a
  // worse default than the constant it replaced.
  await page.keyboard.press("[");
  await page.waitForSelector(".rv__queue");
  const set = (await queue.boundingBox())!.width;
  await page.reload();
  await page.waitForSelector(".qitem");
  expect((await queue.boundingBox())!.width).toBeCloseTo(set, 0);
});

test("the product overview says how much there is before which one to open", async ({ page }) => {
  await signIn(page, EDITOR);

  /* "Overview" used to be a title, a sentence and a list of features — which
     answers "which feature do I open?" without ever answering the question a PM
     asks first: how much is there, and how much of it is mine to do. */
  const labels = await page.locator(".stat__label").allInnerTexts();
  expect(labels.map((label) => label.toLowerCase().trim())).toEqual([
    "features",
    "claims extracted",
    "needs review",
    "unresolved conflicts",
  ]);

  // Every figure is `ScopeCounts` off the projection, the same datum the rail
  // reads. The failure mode a dashboard invites is not a missing number but a
  // number derived a second way, which then disagrees with the rail beside it.
  const navBadge = page
    .locator(".rail__nav-item", { hasText: "Conflicts" })
    .locator(".rail__badge");
  if (await navBadge.count()) {
    const fromRail = Number((await navBadge.innerText()).trim());
    const fromTile = Number(
      (await page.locator(".stat").nth(3).locator(".stat__n").innerText()).trim(),
    );
    expect(fromTile).toBe(fromRail);
  }

  // The dive-in is still one click, and it goes to the most urgent feature.
  await expect(page.locator(".dash__meter .action--primary")).toBeVisible();
});

test("the theme control offers a real light mode, not only the OS reading", async ({ page }) => {
  await openFirstFeature(page, EDITOR);

  const toggle = page.getByRole("button", { name: /theme/i });
  await toggle.click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");

  // The reviewer arrives from Jira and Confluence, both light. Their OS
  // preference is not the same thing as their preference for this app.
  const background = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  expect(background).toBe("rgb(250, 250, 251)");
});

/* --- the public half and the Sources screen (slice 2B) ---------------------
 *
 * These exist for the same reason the rest of the file does. Checking these
 * screens in a browser found four things typecheck and build both called clean:
 * anchors wearing `.action` rendering as underlined buttons, two links stacked
 * on top of each other in the rail, form fields inheriting the *label's*
 * monospace uppercase styling, and — the one that mattered — a run returning 404
 * from `GET /runs/:id` for its entire duration, because the request's session
 * committed only after the background task finished.
 */

test("the front door explains the product before asking for a credential", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");

  await expect(page.locator(".hero__title")).toBeVisible();
  // The three promises that govern what happens after sign-in are on the page
  // someone reads *before* handing over a token, not in a settings screen after.
  await expect(page.getByText("Never writes back.")).toBeVisible();
  expect(errors).toEqual([]);
});

test("a private route with no session goes to sign-in, not a blank page", async ({ page }) => {
  await page.context().clearCookies();
  await page.goto("/app");

  await expect(page).toHaveURL(/\/signin$/);
  await expect(page.getByLabel("Your name")).toBeVisible();
});

/* The hero demo is the page's main argument, so it gets asserted like a
 * feature rather than like decoration. Two things must hold: the claim on
 * screen always has its verbatim excerpt beside it (a demo that showed a claim
 * with no receipt would be advertising the opposite of the product), and the
 * autoplay yields the moment a reader touches it.
 *
 * Driving it by click rather than by waiting on the timer keeps this off the
 * clock — the one assertion that does involve time checks that nothing moved.
 */
test("the hero demo shows every claim with its source excerpt, and yields when driven", async ({
  page,
}) => {
  await page.goto("/");
  const demo = page.locator(".ld-frame");
  await expect(demo).toBeVisible();

  const claims = demo.locator(".ld-qitem");
  await expect(claims).toHaveCount(4);

  for (let i = 0; i < 4; i++) {
    await claims.nth(i).click();
    await expect(demo.locator(".ld-claim")).not.toBeEmpty();
    // The marked span is the excerpt the claim was drawn from. No claim in the
    // demo is allowed to appear without one.
    await expect(demo.locator(".ld-quote mark")).toBeVisible();
  }

  // One pair of claims contradicts the other, and the demo must surface that
  // rather than quietly showing four agreeable ones. Selected by its text
  // rather than by index: the queue is grouped the way the app groups it
  // ("What it must do" / "How it was decided" / "Unresolved"), so a claim's
  // position in the list is a property of its *type*, not something a test
  // should be pinning.
  await demo.locator(".ld-qitem", { hasText: "runs on every file" }).click();
  await expect(demo.locator(".ld-flag")).toBeVisible();
  // Both sides, and the refusal to choose between them, stated on the screen.
  await expect(demo.locator(".ld-flag__side")).toHaveCount(2);
  await expect(demo.locator(".ld-flag")).toContainText("Confirming one side does not settle this");

  // A click hands control to the reader, and it stays handed over.
  const badge = demo.locator(".ld-frame__live");
  await expect(badge).toHaveText("▸ resume");
  const held = await demo.locator(".ld-claim").innerText();
  await page.waitForTimeout(4000);
  await expect(demo.locator(".ld-claim")).toHaveText(held);

  // ...but not irreversibly. The badge is the way back, which is the whole
  // reason it is a button: a reader who paused to read one claim should not
  // have to reload the page to see the loop run again.
  await badge.click();
  await expect(badge).toHaveText("auto-playing");
});

/* The tab strip is the demo's manual control. It exists because an
 * auto-advancing panel offers a reader nothing that looks clickable, so the
 * two things asserted here are exactly the two that make it useful: a tab
 * selects the claim it names, and the strip tracks whatever is on the stage —
 * including while autoplay is the one moving it.
 */
test("the hero demo's tabs select claims, and follow autoplay when it is driving", async ({
  page,
}) => {
  await page.goto("/");
  const tabs = page.locator(".ld-tab");
  await expect(tabs).toHaveCount(4);
  await expect(tabs).toHaveText(["Requirement", "Decision", "Constraint", "Open question"]);

  // Autoplay owns the strip until someone touches it: the active tab is
  // whichever claim the timer has reached, not a fixed first tab.
  await expect(page.locator(".ld-tab.is-active")).toHaveCount(1);

  // The fourth claim is the open question, and it is the one furthest from
  // where autoplay starts — picking it proves the tab drove the stage rather
  // than the timer happening to land there.
  await tabs.nth(3).click();
  await expect(page.locator(".ld-claim")).toContainText("--pre-glob be repeated");
  await expect(tabs.nth(3)).toHaveClass(/is-active/);
  await expect(tabs.nth(3)).toHaveAttribute("aria-selected", "true");
});

/* The demo claims to be a picture of the review screen, and the whole reason it
 * is live DOM rather than a PNG is that a PNG goes stale silently. That only
 * pays off if something notices when the app moves and the demo doesn't — which
 * is what this test is. It pins the two structures that actually drifted:
 * the rail's destinations (About was added to the app and missing here for a
 * fortnight) and the queue's plain-English group headings.
 */
test("the hero demo draws the application the app actually is", async ({ page }) => {
  await page.goto("/");
  const demo = page.locator(".ld-frame");

  // The rail's destinations, in the app's order. `App.tsx` renders exactly
  // these four for a real product.
  await expect(demo.locator(".ld-rail__nav")).toHaveText([
    /^Overview$/,
    /^About$/,
    /^Sources$/,
    /^Conflicts1$/,
  ]);

  // The queue groups claims by what a person calls them, not by the storage
  // enum — these are `GROUPS` in review.ts.
  await expect(demo.locator(".ld-qgroup__label")).toHaveText([
    "What it must do",
    "How it was decided",
    "Unresolved",
  ]);

  // The screen's own title bar, which replaced a fake window title. Both
  // figures are shown because they count different things, exactly as the app
  // does.
  await expect(demo.locator(".ld-rvbar__title")).toHaveText("Preprocessor flag");
  await expect(demo.locator(".ld-rvbar__conflicts")).toContainText("2 claims in 1 conflict");
});

/* Each tab has to argue something different, or the strip is four labels over
 * one picture. The mechanism is a sentence plus a spotlight on the region of
 * the frame that carries the argument, and the two things worth asserting are
 * that the sentence changes and that exactly one region is ever lit — a second
 * spotlight would mean the reader is being pointed at two things at once,
 * which is the same as being pointed at nothing.
 */
test("each claim type in the hero demo spotlights a different part of the screen", async ({
  page,
}) => {
  await page.goto("/");
  const tabs = page.locator(".ld-tab");
  const seen = new Set<string>();

  for (let i = 0; i < 4; i++) {
    await tabs.nth(i).click();
    await expect(page.locator(".ld-shell .is-spot")).toHaveCount(1);
    const lens = await page.locator(".ld-lens").innerText();
    expect(lens.length).toBeGreaterThan(40);
    seen.add(lens);
  }
  expect(seen.size).toBe(4);
});

/* The page used to end at "confirm", because until the About page and the
 * Markdown export shipped there was nothing to show afterwards. The section
 * asserts the two halves of what shipped, and the one rule that makes the
 * export honest rather than merely short.
 */
test("the landing page shows what confirming produces, page and file", async ({ page }) => {
  await page.goto("/");
  const spec = page.locator("#spec");
  await expect(spec).toBeVisible();

  // The page half quotes its source and says what it is still missing.
  await expect(spec.locator(".ld-about__ex").first()).not.toBeEmpty();
  await expect(spec.locator(".ld-about__note")).toContainText("awaiting review");

  // The file half carries provenance inline and lists the unsettled
  // disagreement rather than picking a side.
  const file = spec.locator(".ld-md");
  await expect(file).toContainText("SCRUM-14");
  await expect(file).toContainText("Open disagreements");
  await expect(file).toContainText("Neither side has been rejected");
});

test("buttons on the landing page are not underlined links", async ({ page }) => {
  // `.action` is worn by both <button> and <a>; without an explicit
  // `text-decoration: none` the anchor form renders as an underlined button.
  // The landing page's primary is `.action--brand` (the gradient variant) —
  // `.action--primary` stays the in-product one.
  await page.goto("/");
  const decoration = await page
    .locator(".hero__actions .action--brand")
    .evaluate((element) => getComputedStyle(element).textDecorationLine);

  expect(decoration).toBe("none");
});

test("the sources screen states the read-only promise and never shows a secret", async ({
  page,
}) => {
  await signIn(page, EDITOR);
  // Sources is now a product-level nav entry, alongside Overview and Conflicts.
  await page.locator(".rail__nav-item", { hasText: "Sources" }).click();

  await expect(page.getByRole("heading", { name: "Sources" })).toBeVisible();
  await expect(page.getByText(/never writes to GitHub or Jira/)).toBeVisible();
  // Whatever is connected, the page renders a masked hint and nothing longer.
  for (const hint of await page.locator(".mono-hint").allTextContents()) {
    expect(hint).toMatch(/^••••.{0,4}$/);
  }
});

test("the connect form says where the credential goes before asking for it", async ({ page }) => {
  await signIn(page, ADMIN);
  await page.locator(".rail__nav-item", { hasText: "Sources" }).click();
  await page.getByRole("button", { name: "Connect a source" }).click();

  await expect(page.getByText(/Stored encrypted, and never shown again/)).toBeVisible();
  // The token field must be a password field: a credential typed in the clear is
  // a credential in a screen recording.
  await expect(page.locator("#secret")).toHaveAttribute("type", "password");
});

test("switching the connect form to Jira asks for the email the token belongs to", async ({
  page,
}) => {
  await signIn(page, ADMIN);
  await page.locator(".rail__nav-item", { hasText: "Sources" }).click();
  await page.getByRole("button", { name: "Connect a source" }).click();
  await page.getByRole("button", { name: "Jira", exact: true }).click();

  // Jira Cloud authenticates email + token; asking for one without the other is
  // a connection that can only fail on its first run.
  await expect(page.locator("#email")).toBeVisible();
});

test("an editor can pull from sources but not connect one", async ({ page }) => {
  await signIn(page, EDITOR);
  await page.locator(".rail__nav-item", { hasText: "Sources" }).click();
  await expect(page.locator("h2", { hasText: "Connected" })).toBeVisible();

  // Granting Atlas access is an admin's act (Phase 4); the server refuses it
  // regardless, and the screen does not offer what would be refused.
  await expect(page.getByRole("button", { name: "Connect a source" })).toHaveCount(0);
});

test("connecting Google Docs asks for sharing, never for a token", async ({ page }) => {
  await signIn(page, ADMIN);
  await page.locator(".rail__nav-item", { hasText: "Sources" }).click();
  await page.getByRole("button", { name: "Connect a source" }).click();
  await page.getByRole("button", { name: "Google Docs", exact: true }).click();

  // Sharing is the grant, so there is no credential field to fill in -- and
  // the form says who to share with, or that this Atlas has no Google account.
  await expect(page.locator("#secret")).toHaveCount(0);
  await expect(page.locator("#host")).toHaveCount(0);
  await expect(page.locator("#scope")).toBeVisible();
  await expect(
    page.locator(".connect").getByText(/Share each doc|isn't set up for this workspace/),
  ).toBeVisible();
});

/* --- the guided tour ---------------------------------------------------------
 *
 * Read-only: the tour navigates and reads, and writes nothing but a localStorage
 * flag in its own browser context. Safe to run against the shared workspace.
 *
 * What this actually guards is the **anchors**. A tour step finds its element by
 * `data-tour` and *skips itself* when the element is missing — deliberately, so
 * the tour survives products that have no conflicts. The cost of that mercy is
 * that deleting a `data-tour` attribute during a refactor silently shortens the
 * tour instead of breaking anything, and nobody would notice until a demo. So
 * the test walks every step and asserts each one found something to point at.
 */

test("the guided tour opens on a first visit and spotlights every step", async ({ page }) => {
  await wantTour(page);
  await signInOnly(page, EDITOR);
  // A fresh context has never seen it, so it opens itself.
  await page.waitForSelector(".tour__card", { timeout: 40000 });

  const total = Number(
    ((await page.locator(".tour__step").textContent()) ?? "1 of 1").split(" of ")[1],
  );
  expect(total).toBeGreaterThanOrEqual(4);

  for (let step = 1; step <= total; step++) {
    await page.waitForSelector(".tour__card", { timeout: 40000 });
    await expect(page.locator(".tour__step")).toHaveText(`${step} of ${total}`);
    // The spotlight only renders once an anchor has been measured, so its
    // presence *is* the assertion that this step found its element.
    await expect(page.locator(".tour__hole")).toBeVisible();
    await expect(page.locator(".tour__title")).not.toBeEmpty();
    await page.locator(".tour__row .action--primary").click();
    await page.waitForTimeout(400);
  }

  await expect(page.locator(".tour__card")).toHaveCount(0);
});

test("a browser that has seen the tour is not shown it again, but can replay it", async ({
  page,
}) => {
  /* No `wantTour` here: the opt-out in `beforeEach` *is* the returning browser's
     state, which is the case under test. Reloading with the flag cleared cannot
     test this — the init script would clear it again on every load. */
  await signInOnly(page, EDITOR);
  await page.waitForSelector(".switcher__trigger", { timeout: 40000 });
  // Long enough for the rail to resolve, which is what arms the auto-open.
  await page.waitForTimeout(4000);
  await expect(page.locator(".tour__card")).toHaveCount(0);

  await page.getByRole("button", { name: "Show me around" }).click();

  await expect(page.locator(".tour__card")).toBeVisible();
  await expect(page.locator(".tour__step")).toContainText("1 of");
});

/* --- the About page ---------------------------------------------------------
 *
 * Read-only, like almost everything above: these open the page and read it. The
 * one property worth checking in a real browser is the one the type system
 * cannot see — that the page shows a claim's *source text*, not a paraphrase of
 * it, and that a draft is nowhere on the page.
 */

test("About says what the product is and shows where each claim came from", async ({ page }) => {
  await signIn(page, EDITOR);
  await page.locator('[data-tour="nav-about"]').click();

  await expect(page.locator("h1")).not.toBeEmpty();
  const claims = page.locator(".about__claim");
  if ((await claims.count()) === 0) {
    /* A product where nothing has been confirmed renders the honest empty
       state rather than a blank page, and that is worth asserting too — it is
       the state every new product starts in. */
    await expect(page.locator(".about__nothing").first()).toBeVisible();
    return;
  }
  // Every claim carries its excerpt and a link out to the artifact it came
  // from. A claim rendered without provenance is the bug this product exists
  // to prevent, so it is checked on the page and not only in the assembly.
  await expect(claims.first().locator(".about__ex")).toBeVisible();
  await expect(claims.first().locator(".about__link")).toHaveAttribute("href", /^https?:\/\//);
});

test("About never shows a claim nobody has ruled on", async ({ page }) => {
  await signIn(page, EDITOR);

  // Take an unreviewed claim's text off the review screen…
  await page.locator(".rail__item").first().click();
  await page.waitForSelector(".qitem__text", { timeout: 40000 });
  const unruled = page.locator(".qitem:not(.qitem--reviewed) .qitem__text").first();
  if ((await unruled.count()) === 0) test.skip();
  const draft = ((await unruled.textContent()) ?? "").trim();

  // …and assert it is absent from the assembled document.
  await page.locator('[data-tour="nav-about"]').click();
  await page.waitForSelector(".about__provenance-note", { timeout: 40000 });

  expect(draft.length).toBeGreaterThan(10);
  await expect(page.locator(".about")).not.toContainText(draft);
});

test("a disagreement on About shows both sides, and says it is unresolved", async ({ page }) => {
  await signIn(page, EDITOR);
  await page.locator('[data-tour="nav-about"]').click();
  await page.waitForSelector(".about__provenance-note", { timeout: 40000 });

  const pairs = page.locator(".about__vs");
  if ((await pairs.count()) === 0) test.skip();

  await expect(page.locator(".about__heading--conflict").first()).toBeVisible();
  // Both sides on screen together — the thing the old inline conflict banner
  // could not do, and the reason a disagreement is an object here too.
  await expect(pairs.first().locator(".about__vs-side")).toHaveCount(2);
  // Stated once for the section, not repeated over every pair.
  await expect(page.locator(".about__vs-why").first()).toContainText("does not resolve");
});

test("the spec export downloads as Markdown containing the confirmed claims", async ({ page }) => {
  await signIn(page, EDITOR);
  await page.locator('[data-tour="nav-about"]').click();
  await page.waitForSelector(".about__provenance-note", { timeout: 40000 });

  const download = page.getByRole("link", { name: "Download" });
  if ((await download.count()) === 0) test.skip(); // nothing confirmed to export

  const claim = ((await page.locator(".about__claim-text").first().textContent()) ?? "").trim();
  const [file] = await Promise.all([page.waitForEvent("download"), download.click()]);

  expect(file.suggestedFilename()).toMatch(/-spec\.md$/);
  const stream = await file.createReadStream();
  const chunks: Buffer[] = [];
  for await (const chunk of stream) chunks.push(Buffer.from(chunk));
  const markdown = Buffer.concat(chunks).toString("utf8");

  expect(markdown).toContain("# ");
  // The export and the page are one assembly rendered twice; if this fails, the
  // confirmed-only filter has been reimplemented somewhere it should not be.
  expect(markdown).toContain(claim.replace(/\s*edited$/, ""));
});

/* --- 2026-09-28: readiness, versioning, Q&A, quality ----------------------
 *
 * Read-only again. The Ask box is checked for presence and wiring only: a real
 * question would spend tokens on every run, and the answer's guarantees are
 * pinned server-side in tests/test_qa.py.
 */

test("About states the spec's readiness and links every gap somewhere", async ({ page }) => {
  await signIn(page, EDITOR);
  await page.locator('[data-tour="nav-about"]').click();
  await page.waitForSelector(".about__provenance-note", { timeout: 40000 });

  const panel = page.locator(".readiness");
  await expect(panel).toBeVisible();
  await expect(panel.locator(".readiness__score")).toHaveText(/^\d{1,3}$/);
  await expect(panel.locator(".readiness__sub")).toContainText(/\d+ of \d+ checks pass/);
  // A number with nothing to click is a grade, not a to-do list.
  const gaps = panel.locator(".readiness__gap a");
  for (let index = 0; index < (await gaps.count()); index++) {
    await expect(gaps.nth(index)).toHaveAttribute("href", /^\/p\//);
  }
});

test("About offers what changed and a question box once something is confirmed", async ({
  page,
}) => {
  await signIn(page, EDITOR);
  await page.locator('[data-tour="nav-about"]').click();
  await page.waitForSelector(".about__provenance-note", { timeout: 40000 });
  if ((await page.locator(".about__claim").count()) === 0) test.skip();

  const changes = page.locator(".changes");
  await expect(changes).toBeVisible();
  await changes.getByRole("tab", { name: "30 days" }).click();
  await expect(changes.getByRole("tab", { name: "30 days" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await expect(changes.locator(".changes__summary")).toBeVisible();

  const ask = page.locator(".ask");
  await expect(ask.locator(".ask__input")).toBeVisible();
  // Disabled until there is a question, so an empty click cannot spend a call.
  await expect(ask.getByRole("button", { name: "Ask" })).toBeDisabled();
});

test("Quality reads the rulings and states the guard above the numbers", async ({ page }) => {
  await signIn(page, EDITOR);
  const link = page.locator(".rail__nav-item", { hasText: "Quality" });
  await expect(link).toBeVisible();
  await link.click();
  await expect(page).toHaveURL(/\/quality$/);

  await expect(page.locator("h1")).toHaveText("Extraction quality", { timeout: 40000 });
  await expect(page.locator(".about__provenance-note")).toContainText("first read");
  // Either a headline rate or the honest empty state -- never a blank page.
  await expect(page.locator(".quality__headline, .notice").first()).toBeVisible();
});
