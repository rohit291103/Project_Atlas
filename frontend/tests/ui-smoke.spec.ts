/* Real-browser smoke test for the confirmation UI.
 *
 * This suite exists because `tsc` and `vite build` both passed while three real
 * defects sat in the rendered page: a viewer was shown keyboard shortcuts that
 * did nothing, expanding a source excerpt printed it twice, and a reviewed card
 * kept a full-loud conflict banner so *done* work was the noisiest thing on
 * screen. None of those are type errors. They are only visible when something
 * renders the page and looks at it.
 *
 * Requires the API running against a seeded database (see playwright.config.ts).
 * The assertions below are about behaviour the specs actually promise, not about
 * pixel positions — a layout test that breaks on every padding change teaches
 * people to ignore it.
 */

import { expect, test } from "@playwright/test";

const EDITOR = "Priya (PM)";
const VIEWER = "Sam";
const PASSPHRASE = process.env.ATLAS_APP_PASSPHRASE ?? "letmein";

type Page = import("@playwright/test").Page;

/** Focus a card by clicking its header row. Clicking the card *body* lands on
 * whatever control sits at its centre — the first version of this suite
 * confirmed nodes by accident that way, and then failed on the state it had
 * silently created. */
async function focusCard(card: import("@playwright/test").Locator) {
  await card.locator(".card__head").click();
}

async function signIn(page: Page, name: string) {
  await page.goto("/");
  await page.getByLabel("Your name").fill(name);
  await page.getByLabel("Passphrase").fill(PASSPHRASE);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForSelector(".scope-header__title");
}

test("the page renders without console errors once signed in", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await signIn(page, EDITOR);
  expect(errors).toEqual([]);
});

test("a feature scope reads as an assembly of its sources", async ({ page }) => {
  await signIn(page, EDITOR);

  await expect(page.locator(".scope-header__title")).not.toBeEmpty();
  // The cross-source thesis, visible: one feature, more than one tool feeding it.
  await expect(page.locator(".assembled .badge")).toHaveCount(2);
  await expect(page.locator(".meter")).toContainText("reviewed");
});

test("a cross-source conflict names the other side's tool", async ({ page }) => {
  await signIn(page, EDITOR);

  // The thing no single tool could have surfaced — so it must say which tool.
  await expect(page.locator(".conflict").filter({ hasText: "in Jira" })).not.toHaveCount(0);
});

test("provenance expands without repeating itself", async ({ page }) => {
  await signIn(page, EDITOR);
  const card = page.locator(".card").first();
  await focusCard(card);

  const toggle = card.locator(".provenance__toggle").first();
  await expect(toggle).toHaveText(/^▸/);
  await toggle.click();

  // Expanded, the well carries the excerpt and the toggle line steps aside —
  // it used to print the same words twice, once clipped and once in full.
  await expect(card.locator(".provenance__well")).toHaveCount(1);
  await expect(toggle).toHaveText(/hide excerpt/);
});

test("confirming moves the meter and recedes the card", async ({ page }) => {
  await signIn(page, EDITOR);
  // Whatever earlier tests left behind, act on something still to review.
  const pending = page.locator(".card").filter({ hasText: "to review" }).first();
  const claim = await pending.locator(".card__claim").innerText();
  const reviewedBefore = await page.locator(".card--reviewed").count();

  await focusCard(pending);
  await page.getByRole("button", { name: /Confirm/ }).click();
  await expect(page.locator(".card--reviewed")).toHaveCount(reviewedBefore + 1);
  await expect(page.locator(".card--reviewed").filter({ hasText: claim })).toHaveCount(1);

  // A reviewed card still shows its conflict, but compactly — surfaced, not shouted.
  await focusCard(page.locator(".card").filter({ hasText: "to review" }).first());
  await expect(
    page.locator(".card--reviewed:not(.card--focused) .conflict:not(.conflict--compact)"),
  ).toHaveCount(0);
});

test("a viewer is shown no write affordances at all", async ({ page }) => {
  await signIn(page, VIEWER);
  await focusCard(page.locator(".card").first());

  await expect(page.locator(".actions")).toHaveCount(0);
  // Not just the buttons: advertising `c confirm` to a viewer teaches a shortcut
  // that silently does nothing.
  await expect(page.locator(".hints")).toContainText("read-only");
  await expect(page.locator(".hints")).not.toContainText("confirm");
});

test("the add composer never asks for a citation", async ({ page }) => {
  await signIn(page, EDITOR);
  await page.keyboard.press("a");
  await page.waitForSelector(".composer textarea");

  // PRD R10 + the manual-provenance decision: the evidence is the person who
  // typed it. Asking for a URL is how fabricated provenance gets in.
  await expect(page.locator(".composer")).toContainText("asserted by");
  await expect(page.locator(".composer")).not.toContainText(/url|https?:/i);
});
