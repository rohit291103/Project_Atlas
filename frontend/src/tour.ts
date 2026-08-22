/* The guided first run: what to look at, in the order the product's argument
 * makes sense.
 *
 * A PM opening Atlas for the first time sees a rail, a grid of numbers and a
 * three-pane review screen, and none of it says which part matters first. The
 * storyline this walks is the one the product is actually about:
 *
 *     a product → what it is → how much is waiting → one feature →
 *     one claim → where that claim came from → the two sources that
 *     disagree → your ruling
 *
 * **Anchored to the UI, not to the demo.** Every step names a `data-tour`
 * attribute and a route, never a product or feature id, so the same tour runs
 * on the Plausible demo, on ripgrep, and on the first product a PM connects
 * themselves. A step whose anchor is not on screen — no conflicts in this
 * product, no description written yet — is skipped rather than pointing at
 * nothing, which is what makes "works for any product" true rather than
 * aspirational.
 *
 * Shown once per browser, like `lastProduct`, and replayable from the rail.
 * Deliberately localStorage rather than server state: whether *this browser*
 * has seen the tour is not a fact about the workspace, and a PM who signs in on
 * a borrowed laptop to be measured should get the tour there too.
 */

import type { Route } from "./router";

const KEY = "atlas.tourSeen";

export function hasSeenTour(): boolean {
  try {
    return window.localStorage.getItem(KEY) === "1";
  } catch {
    // Private-mode Safari throws. Never showing the tour is a downgrade;
    // taking the app down with it is not an option.
    return true;
  }
}

export function markTourSeen(): void {
  try {
    window.localStorage.setItem(KEY, "1");
  } catch {
    /* see above */
  }
}

export type TourStep = {
  id: string;
  /** The `data-tour` value to spotlight. Absent from the DOM ⇒ step skipped. */
  anchor: string;
  title: string;
  body: string;
  /** Where this step lives. The tour navigates here before looking for the
   *  anchor, so a step can be on a screen the reviewer has not opened yet. */
  route: Route;
  /** Which side of the anchor the card prefers; it flips if there is no room. */
  place?: "right" | "left" | "top" | "bottom";
};

/** The steps, resolved against whichever product and feature we are pointing at.
 *
 * `featureId` is chosen by the caller — the feature with the most disagreement,
 * because the conflict steps are the ones with something to show. With no
 * features at all the feature-level steps are dropped here rather than being
 * left to fail their anchor lookups one by one.
 */
export function tourSteps(productId: string, featureId: string | null): TourStep[] {
  const product: Route = { name: "product", productId };
  const steps: TourStep[] = [
    {
      id: "product-card",
      anchor: "product-card",
      title: "This is a product",
      body:
        "One product is one thing you work on — its own GitHub org, its own Jira site, its "
        + "own features. Nothing crosses between them. Click it, or press Next, to go in.",
      route: { name: "products" },
      place: "bottom",
    },
    {
      id: "product-what",
      anchor: "product-what",
      title: "Start with what this is",
      body:
        "A product is one thing you work on — its own sources, its own features, nothing "
        + "shared with the others. This line is written by a person, not extracted, so it "
        + "says what the product is for rather than what a tool called it.",
      route: product,
      place: "bottom",
    },
    {
      id: "product-counts",
      anchor: "product-counts",
      title: "Then how much is yours to do",
      body:
        "Every claim Atlas extracted is a draft until someone rules on it. These four "
        + "numbers are the whole job: what was found, what still needs a person, and where "
        + "two sources disagree.",
      route: product,
      place: "bottom",
    },
    {
      id: "worklist",
      anchor: "worklist",
      title: "The queue, disagreements first",
      body:
        "Features that need a ruling sit at the top, and the ones with a conflict come "
        + "first inside that — because a disagreement between two sources is the thing "
        + "only a person can settle.",
      route: product,
      place: "top",
    },
  ];

  if (!featureId) return steps;

  const feature: Route = { name: "feature", productId, featureId };
  return [
    ...steps,
    {
      id: "feature-what",
      anchor: "feature-what",
      title: "Inside a feature",
      body:
        "The title came from whichever ticket or pull request opened this feature, so it "
        + "says what it was called. The line under it is what it is for. Everything below "
        + "was pulled out of the sources automatically.",
      route: feature,
      place: "bottom",
    },
    {
      id: "claim",
      anchor: "claim",
      title: "One claim at a time",
      body:
        "A goal, a requirement, a decision, a constraint — typed, and each one a separate "
        + "thing you can accept or throw away. Nothing here is settled: it is a draft "
        + "until you act on it.",
      route: feature,
      place: "right",
    },
    {
      id: "provenance",
      anchor: "provenance",
      title: "Where it came from",
      body:
        "Every claim carries the literal sentence it was taken from, and a link to the "
        + "ticket or pull request it lives in. Never a paraphrase — that is what makes a "
        + "claim checkable in a few seconds instead of taken on trust.",
      route: feature,
      place: "left",
    },
    {
      id: "nav-conflicts",
      anchor: "nav-conflicts",
      title: "Where two sources disagree",
      body:
        "This is the count of disagreements — places where the ticket and the pull request "
        + "say different things about the same feature. Atlas never picks a winner and never "
        + "quietly merges them.",
      route: feature,
      place: "right",
    },
    {
      /* Anchored on the Conflicts screen rather than on the review screen's
         own conflict panel: there, both sides only appear when the *focused*
         claim happens to be one of them, so the step was being skipped on
         exactly the products that had the most to show. */
      id: "conflict-pair",
      anchor: "conflict-pair",
      title: "Both sides, both quotes, nobody overruled",
      body:
        "Each side keeps its own source and its own literal excerpt, and you rule on each "
        + "separately. Ruling on one does not erase the other — the disagreement stays on "
        + "the record, which is the honest thing for a spec to carry.",
      route: { name: "conflicts", productId },
      place: "bottom",
    },
    {
      id: "worklist-again",
      anchor: "worklist",
      title: "That is the loop",
      body:
        "Read a claim, check the quote it came from, accept it or throw it away. Only what "
        + "a person has confirmed counts as settled — nothing extracted is treated as true "
        + "until you say so.",
      route: product,
      place: "top",
    },
    {
      /* The last step, and the one the tour was missing: until now it ended on
         the queue, which told a newcomer what the work *is* and never what it
         produces. Anchored on the rail entry rather than on anything inside the
         page, because the page is empty on a product where nothing has been
         confirmed yet — which is exactly the state a first-time visitor is in,
         and the step should still be shown to them. */
      id: "about",
      anchor: "nav-about",
      title: "And this is what it is all for",
      body:
        "Everything you confirm collects here as a written account of the product — every "
        + "claim under the feature it belongs to, each one still carrying the source text it "
        + "came from. Copy it or download it as Markdown and hand it to a coding agent. "
        + "Drafts never reach it, and a disagreement nobody has settled arrives saying so.",
      route: { name: "about", productId },
      place: "right",
    },
  ];
}

/** Which feature to walk the reviewer through: the one with the most conflicts,
 * else the one with the most left to review, else the first.
 *
 * The tour is only worth taking on a feature that has something to show, and on
 * a product mid-review the emptiest feature is the likeliest first row.
 */
export function tourFeature<T extends { id: string; counts: { conflicts: number; unreviewed: number } }>(
  features: readonly T[],
): string | null {
  if (features.length === 0) return null;
  const ranked = [...features].sort(
    (a, b) =>
      b.counts.conflicts - a.counts.conflicts || b.counts.unreviewed - a.counts.unreviewed,
  );
  return ranked[0]!.id;
}
