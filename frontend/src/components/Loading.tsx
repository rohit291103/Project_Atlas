/* The boot screen.
 *
 * `App` used to render `<div className="entry" />` while the session check was
 * in flight — a correct decision (don't bounce a returning reviewer to /signin
 * during the moment we don't yet know who they are) rendered as a blank page.
 * On a cold load against a remote database that blank is the entire first
 * impression, and a blank page is indistinguishable from a broken one.
 *
 * The mark is drawn here rather than reusing `<AtlasMark>` because it needs to
 * be stroked with the brand ramp, which `currentColor` cannot carry. Same three
 * paths as `Logo.tsx`, scaled from their 16-unit grid into this 100-unit one and
 * centred, inside the same travelling-arc ring the loop diagram uses.
 * The arc's dash geometry lives in styles.css so the global
 * prefers-reduced-motion rule can stop it; when it does, the ring is still a
 * ring and the label still says what is happening.
 */

export function Loading({ label = "Loading your workspace" }: { label?: string }) {
  return (
    <div className="boot" role="status" aria-live="polite">
      <div className="boot__mark">
        <svg viewBox="0 0 100 100" aria-hidden focusable="false">
          <defs>
            <linearGradient id="atlas-boot-line" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stopColor="var(--brand-1)" />
              <stop offset="50%" stopColor="var(--brand-2)" />
              <stop offset="100%" stopColor="var(--brand-3)" />
            </linearGradient>
          </defs>
          <circle className="boot__track" cx="50" cy="50" r="44" />
          <circle className="boot__spark" cx="50" cy="50" r="44" />
          {/* translate(18 18) scale(4) maps the mark's 16×16 grid onto the
              middle 64 units of this 100-unit box. The stroke is set here
              rather than scaled with it, so it stays the ring's weight. */}
          <g className="boot__glyph" transform="translate(18 18) scale(4)">
            <path d="M1 8h14" />
            <path d="M1 3h3l5 5" />
            <path d="M1 13h3l5-5" />
          </g>
        </svg>
      </div>
      <p className="boot__label">{label}</p>
    </div>
  );
}
