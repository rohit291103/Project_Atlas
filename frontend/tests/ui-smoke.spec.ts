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

/* Actors come from the environment because membership is per-database: the local
 * seed has `Priya (PM)` and `Sam`, the live workspace has whoever was actually
 * granted a role. Hardcoding them meant the suite could only ever run against
 * one of the two, and it was silently the one nobody was using. A workspace with
 * no viewer skips the viewer test rather than failing it — that is a fact about
 * the database, not a defect in the page. */
const EDITOR = process.env.ATLAS_TEST_EDITOR ?? "Priya (PM)";
const VIEWER = process.env.ATLAS_TEST_VIEWER ?? "";
const PASSPHRASE = process.env.ATLAS_APP_PASSPHRASE ?? "letmein";

type Page = import("@playwright/test").Page;

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
  // Order follows the loop the product runs — connect, then review — rather
  // than the order the screens happened to be built in.
  await expect(page.locator(".rail__nav-item")).toHaveText([
    /^Overview$/,
    /^Sources$/,
    /^Conflicts\d*$/,
  ]);
  // ...and the groups are labelled with the same verbs the landing page and the
  // sign-in panel use, so the product speaks one vocabulary.
  await expect(page.locator(".rail__group-label")).toHaveText(["Connect", "Review", "Features"]);
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

  // Signing out lands on the marketing page, not the form; `signInOnly` goes
  // to /signin itself, so there is nothing to wait for in between.
  await page.getByText("Sign out").click();
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

  // Conflicts is counted as disagreements, so the nav badge and the dashboard
  // summary line must be the same figure.
  const navBadge = page
    .locator(".rail__nav-item", { hasText: "Conflicts" })
    .locator(".rail__badge");
  if (await navBadge.count()) {
    const navCount = Number((await navBadge.innerText()).trim());
    const sub = await page.locator(".page-sub").innerText();
    const fromSummary = Number(/(\d+)\s+conflicts?/.exec(sub)?.[1] ?? "-1");
    expect(fromSummary).toBe(navCount);
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
  // A claim can disagree with more than one other claim, so scope to the first
  // banner rather than asserting across all of them.
  await expect(page.locator(".flagbox").first()).toContainText(/in (Jira|GitHub)/);
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
  test.skip(!VIEWER, "no viewer actor in this workspace (set ATLAS_TEST_VIEWER)");
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

  // The second claim is the one that contradicts the Jira requirement; the
  // demo must surface that rather than quietly showing four agreeable claims.
  await claims.nth(1).click();
  await expect(demo.locator(".ld-flag")).toBeVisible();

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
  await signIn(page, EDITOR);
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
  await signIn(page, EDITOR);
  await page.locator(".rail__nav-item", { hasText: "Sources" }).click();
  await page.getByRole("button", { name: "Connect a source" }).click();
  await page.getByRole("button", { name: "Jira", exact: true }).click();

  // Jira Cloud authenticates email + token; asking for one without the other is
  // a connection that can only fail on its first run.
  await expect(page.locator("#email")).toBeVisible();
});
