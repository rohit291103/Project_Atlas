/* The rail's icons.
 *
 * Not decoration. The rail used to nest each nav item under a mono all-caps
 * group label — "CONNECT" over `Sources`, "REVIEW" over `Conflicts` — and the
 * two read as one flat column of alternating type sizes rather than as headings
 * over children, because every group held exactly one item. A heading over a
 * single child is noise that has to be decoded before it can be dismissed.
 *
 * The fix is to drop those one-item groups and let a leading glyph do the
 * distinguishing instead: a row with an icon is unmistakably a *destination*,
 * and the one remaining section label ("Features") sits over a real list, which
 * is the only place a heading earns its keep. Same vocabulary as before —
 * connect, then review — now carried by the order and the glyphs.
 *
 * Inline SVG rather than an icon package: six paths is not worth a dependency,
 * and `currentColor` + a shared stroke width is what keeps them looking like one
 * family instead of six borrowed drawings.
 */

type IconProps = { className?: string };

const base = {
  width: 16,
  height: 16,
  viewBox: "0 0 16 16",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.5,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
  focusable: false,
};

/** Overview — the product's dashboard. A meter, because that is what the screen is. */
export const IconOverview = ({ className }: IconProps) => (
  <svg {...base} className={className}>
    <rect x="2" y="2" width="5" height="5" rx="1" />
    <rect x="9" y="2" width="5" height="5" rx="1" />
    <rect x="2" y="9" width="5" height="5" rx="1" />
    <rect x="9" y="9" width="5" height="5" rx="1" />
  </svg>
);

/** Sources — a plug. Connecting a tool, which is literally what the screen does. */
export const IconSources = ({ className }: IconProps) => (
  <svg {...base} className={className}>
    <path d="M6 2v3M10 2v3" />
    <path d="M3.5 5h9v2a4.5 4.5 0 0 1-4.5 4.5A4.5 4.5 0 0 1 3.5 7Z" />
    <path d="M8 11.5V14" />
  </svg>
);

/** Conflicts — the one loud thing in the product, so the one filled-ish glyph. */
export const IconConflict = ({ className }: IconProps) => (
  <svg {...base} className={className}>
    <path d="M8 2.5 14 13H2Z" />
    <path d="M8 6.5v3" />
    <path d="M8 11.4h.01" />
  </svg>
);

/** A feature scope — a stack of claims assembled into one thing. */
export const IconFeature = ({ className }: IconProps) => (
  <svg {...base} className={className}>
    <path d="M2.5 5.5 8 2.5l5.5 3L8 8.5Z" />
    <path d="m2.5 10.5 5.5 3 5.5-3" />
  </svg>
);

/** Collapse/expand the claim queue. Direction is set by the caller via CSS. */
export const IconPanel = ({ className }: IconProps) => (
  <svg {...base} className={className}>
    <rect x="2" y="2.5" width="12" height="11" rx="1.5" />
    <path d="M6.5 2.5v11" />
  </svg>
);

/** Open the source document in its own tool. */
export const IconExternal = ({ className }: IconProps) => (
  <svg {...base} className={className}>
    <path d="M9 3h4v4" />
    <path d="M13 3 7.5 8.5" />
    <path d="M11.5 9.5V13h-9V4h3.5" />
  </svg>
);
