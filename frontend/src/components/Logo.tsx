/* The Atlas mark.
 *
 * Three lines enter from the left — a trunk and two tributaries — and one line
 * leaves to the right. Several sources of context converging into one spec,
 * which is the product in a single gesture.
 *
 * ## What it replaced, and why
 *
 * The previous glyph was a circle with an inner meridian: a globe, because the
 * product is called Atlas. That is drawing the *name*, not the thing, and the
 * name is the least interesting fact about this product — the result could
 * equally have belonged to a travel company. Worse, "atlas" as globe is the
 * reading that collides with Atlassian's own Atlas, which ships in every Jira
 * Cloud plan.
 *
 * ## Why these exact three paths
 *
 * Four geometries were drawn and rendered at 16/18/20/24/32/64px in both themes
 * before this one was chosen (see `docs/ux/brand-and-logo-brief-v1.md` §3):
 *
 * - **Curved tributaries** bow outward and read as a wheat sprig, not a
 *   confluence. Organic where this product is precise.
 * - **Four or five tributaries** close up into a smudge below ~20px. The rail
 *   renders this at 16px, so anything that dies there is disqualified whatever
 *   it looks like on a slide.
 * - **A single convergence point** fills in: five stroked paths meeting at one
 *   coordinate paint a solid triangle, and the mark turns into a play button —
 *   *execute*, rather than *these came together*. The two tributaries here meet
 *   the trunk at the same x but never terminate on each other.
 *
 * Straight 45° diagonals survived all three. They also read as *engineered*
 * rather than grown, which is the register the rest of the product is in.
 *
 * Three inbound lines is not an arbitrary count: it is GitHub, Jira, and the
 * third source Phase 3 adds. It stops being literal the day there is a fourth,
 * and "several" is all it has to say by then.
 *
 * Drawn on the same 16×16 grid at the same 1.5 stroke as `icons.tsx`, so the
 * brand and the rail's navigation glyphs are demonstrably one family. It takes
 * `currentColor`, so it themes itself and needs no light/dark variant.
 */

export function AtlasMark({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      focusable="false"
    >
      <path d="M1 8h14" />
      <path d="M1 3h3l5 5" />
      <path d="M1 13h3l5-5" />
    </svg>
  );
}
