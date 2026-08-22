/* The loop diagram — the one section on the page that is a picture, not a
 * screen.
 *
 * Everything else on the landing page shows a surface of the product. This
 * shows the *shape* of it: Atlas is not a one-shot importer, it is a cycle that
 * a feature goes round, and the argument for the cycle is spatial in a way that
 * three paragraphs of prose is not.
 *
 * Four nodes, honestly chosen, and the fourth changed on 2026-08-22. It used to
 * describe only what the confirmed set already *was* and what a person did with
 * it, because spec assembly and export were Phase 2 and unbuilt — a node reading
 * "Atlas generates your spec" would have completed the circle more neatly and
 * been a lie. They shipped (`src/atlas/assembly.py`, `/p/{id}/about`, `GET
 * /products/{id}/spec`), so the node now says what the product does: confirmed
 * claims assemble into a page and a Markdown file, quotes and links intact.
 *
 * Still deliberately *not* claimed is the effect. That handing an agent this
 * file measurably improves what it writes is Phase 2's proof, and that has not
 * been run — the node describes the artifact, never the outcome. The return arc
 * credits the closing of the loop to the team's own work landing as new pull
 * requests and tickets, which is where the next pass starts.
 *
 * Geometry: the ring lives in a 0–100 viewBox at r=30 around (50,50), and the
 * node cards are absolutely positioned at the same radius in percentages — so
 * the two stay locked together at every width without JS measuring anything.
 * Under 900px the whole thing linearises into a vertical rail (see styles.css),
 * because a circle of four cards on a phone is four cards and a hidden circle.
 */

type Stop = {
  key: string;
  n: string;
  title: string;
  body: string;
};

const STOPS: Stop[] = [
  {
    key: "connect",
    n: "01",
    title: "Connect",
    body: "One PR, one epic, one label. Named by you, read with your own credential.",
  },
  {
    key: "extract",
    n: "02",
    title: "Extract",
    body: "An agent emits typed claims. Each one quotes the sentence it came from.",
  },
  {
    key: "confirm",
    n: "03",
    title: "Confirm",
    body: "You confirm, edit or reject one claim at a time, and your name stays on it.",
  },
  {
    key: "handoff",
    n: "04",
    title: "Hand off",
    body: "Confirmed claims assemble into a page and a Markdown spec, quotes and links intact.",
  },
];

/* Angles measured clockwise from twelve o'clock, matching the node positions
   below. The arrowheads sit between the nodes, not on them, so the ring reads
   as travelling rather than as four dots on a circle. */
const ARROWS = [45, 135, 225, 315];

function ring(angle: number, radius = 30) {
  const rad = (angle * Math.PI) / 180;
  return { x: 50 + radius * Math.sin(rad), y: 50 - radius * Math.cos(rad) };
}

export function LoopDiagram() {
  return (
    <>
      <div className="loop__diagram">
        <svg className="loop__ring" viewBox="0 0 100 100" aria-hidden focusable="false">
          <defs>
            <linearGradient id="atlas-loop-line" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stopColor="var(--brand-1)" />
              <stop offset="50%" stopColor="var(--brand-2)" />
              <stop offset="100%" stopColor="var(--brand-3)" />
            </linearGradient>
            <radialGradient id="atlas-loop-glow">
              <stop offset="55%" stopColor="var(--brand-2)" stopOpacity="0" />
              <stop offset="82%" stopColor="var(--brand-2)" stopOpacity="0.22" />
              <stop offset="100%" stopColor="var(--brand-2)" stopOpacity="0" />
            </radialGradient>
          </defs>

          <circle cx="50" cy="50" r="38" fill="url(#atlas-loop-glow)" />
          <circle className="loop__track" cx="50" cy="50" r="30" />
          {/* The travelling arc. Its dash geometry is in styles.css so that the
              global prefers-reduced-motion rule can stop it — an SVG <animate>
              would keep running straight through that preference. */}
          <circle className="loop__spark" cx="50" cy="50" r="30" />

          {ARROWS.map((angle) => {
            const { x, y } = ring(angle);
            return (
              <path
                key={angle}
                className="loop__arrow"
                d="M-1.7,-2.3 L2,0 L-1.7,2.3 Z"
                transform={`translate(${x} ${y}) rotate(${angle})`}
              />
            );
          })}
        </svg>

        <div className="loop__hub">
          <span className="loop__hub-label">one feature</span>
          <strong>at a time</strong>
          <span className="loop__hub-note">never a crawl of your org</span>
        </div>

        <ol className="loop__stops">
          {STOPS.map((stop) => (
            <li key={stop.key} className={`loop__stop loop__stop--${stop.key}`}>
              <span className="loop__n">{stop.n}</span>
              <h3>{stop.title}</h3>
              <p>{stop.body}</p>
            </li>
          ))}
        </ol>
      </div>

      <p className="loop__return">
        <span className="loop__return-arc" aria-hidden />
        The work lands as new pull requests and tickets, which is where the next pass starts.
      </p>
    </>
  );
}
