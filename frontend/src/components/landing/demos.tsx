/* The demo surfaces on the public page.
 *
 * These are the "video" the landing page needed, built as live DOM rather than
 * a recording or a screenshot, for three reasons that all matter here:
 *
 * 1. The app has three themes. A screenshot has one. A PNG of the dark build
 *    dropped into a light page is the single most common way a marketing site
 *    stops looking like the product it sells.
 * 2. Every value below is a token from the same stylesheet the real screens
 *    use, so the demo cannot drift from the product's palette — it *is* the
 *    product's palette. A re-recorded video drifts the day the accent changes.
 * 3. It stays sharp at any width and weighs nothing.
 *
 * The content is the ripgrep `--pre` flag feature from the validation set —
 * the same real example the rest of the page already cites, including the
 * genuine GitHub/Jira conflict the extraction agent found. Nothing here is a
 * capability Atlas doesn't have.
 *
 * Layout mirrors the real review screen (`confirmation-flow-spec-v1`): queue
 * left, one claim centre, evidence right. Class names are `ld-` prefixed
 * because the app's own `.claim`, `.actions`, `.zone` and `.badge` are global
 * and these must not inherit from them by accident.
 */

import { useEffect, useRef, useState } from "react";

type Claim = {
  type: "requirement" | "decision" | "constraint" | "open question";
  source: "GitHub" | "Jira";
  ref: string;
  text: string;
  excerpt: string;
  /* The substring of `excerpt` the extractor keyed on, marked in the quote the
     way the review screen marks it. Must appear verbatim in `excerpt`. */
  mark: string;
  confidence: 1 | 2 | 3;
  conflict?: string;
  /* The edges this claim sits on. Claims are a graph, not a list, and the
     review screen shows the neighbours — so the demo does too, rather than
     leaving the space under the claim empty. */
  relates: string;
};

const CLAIMS: Claim[] = [
  {
    type: "requirement",
    source: "Jira",
    ref: "SCRUM-14",
    text: "The preprocessor must only run on files matching an explicit glob.",
    excerpt:
      "Acceptance: only invoke the preprocessor for paths that match --pre-glob. Everything else goes down the normal search path.",
    mark: "only invoke the preprocessor for paths that match --pre-glob",
    confidence: 3,
    relates: "constrains → the --pre flag · contradicted by a GitHub decision",
  },
  {
    type: "decision",
    source: "GitHub",
    ref: "#1231",
    text: "The preprocessor runs on every file, unmatched by any filter.",
    excerpt:
      "I think we should just run it on everything and let the user sort it out — a filter is one more flag nobody will remember.",
    mark: "just run it on everything",
    confidence: 2,
    relates: "contradicts → the requirement extracted from SCRUM-14",
    conflict: "Contradicts the requirement extracted from SCRUM-14",
  },
  {
    type: "constraint",
    source: "GitHub",
    ref: "#1231",
    text: "Preprocessing must skip files detected as binary.",
    excerpt:
      "One thing though: we should skip anything binary. Running the preproc on a 2GB core dump is a footgun.",
    mark: "we should skip anything binary",
    confidence: 3,
    relates: "constrains → the --pre flag · raised during review of #1231",
  },
  {
    type: "open question",
    source: "Jira",
    ref: "SCRUM-14",
    text: "Can --pre-glob be repeated, or does it take one comma-separated list?",
    excerpt:
      "Unclear whether we want a repeatable --pre-glob or a comma list here — needs a call before implementation.",
    mark: "needs a call before implementation",
    confidence: 2,
    relates: "blocks → the requirement extracted from SCRUM-14",
  },
];

const STEP_MS = 3400;
const PRESS_AT = 2900;

function Pips({ level }: { level: 1 | 2 | 3 }) {
  return (
    <span
      className="ld-pips"
      title={`confidence ${level} of 3`}
      aria-label={`confidence ${level} of 3`}
    >
      {[1, 2, 3].map((n) => (
        <i key={n} className={n <= level ? "is-on" : undefined} />
      ))}
    </span>
  );
}

/* Splits the excerpt around the marked span so the quote can highlight the
   words the claim was actually drawn from, rather than glowing wholesale. */
function MarkedQuote({ excerpt, mark }: { excerpt: string; mark: string }) {
  const at = excerpt.indexOf(mark);
  if (at < 0) return <>{excerpt}</>;
  return (
    <>
      {excerpt.slice(0, at)}
      <mark>{mark}</mark>
      {excerpt.slice(at + mark.length)}
    </>
  );
}

/* ── the hero demo ───────────────────────────────────────────────────────────
 *
 * Autoplays a confirmation pass and loops. It stops when off-screen, when the
 * reader prefers reduced motion, and permanently once the reader clicks a
 * claim themselves — at that point they are driving, and something that keeps
 * moving under a cursor is a bug, not a demo.
 */
export function ReviewDemo() {
  const [index, setIndex] = useState(0);
  const [pressed, setPressed] = useState(false);
  const [driving, setDriving] = useState(false);
  const [inView, setInView] = useState(false);
  const frame = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const node = frame.current;
    if (!node) return;
    const io = new IntersectionObserver(([entry]) => setInView(Boolean(entry?.isIntersecting)), {
      threshold: 0.25,
    });
    io.observe(node);
    return () => io.disconnect();
  }, []);

  const calm =
    typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  const playing = inView && !driving && !calm;

  useEffect(() => {
    if (!playing) return;
    const press = window.setTimeout(() => setPressed(true), PRESS_AT);
    const advance = window.setTimeout(() => {
      setPressed(false);
      setIndex((i) => (i + 1) % CLAIMS.length);
    }, STEP_MS);
    return () => {
      window.clearTimeout(press);
      window.clearTimeout(advance);
    };
  }, [playing, index]);

  const claim = CLAIMS[index]!;
  const done = index;
  const pct = Math.round((done / CLAIMS.length) * 100);

  return (
    <div className="ld-frame" ref={frame}>
      <div className="ld-frame__bar">
        <span className="ld-dots" aria-hidden>
          <i />
          <i />
          <i />
        </span>
        <span className="ld-frame__title">
          Atlas — <b>Preprocessor flag</b> · 4 claims from GitHub + Jira
        </span>
        <span className="ld-frame__live">{playing ? "auto-playing" : "paused"}</span>
      </div>

      <div className="ld-review">
        <aside className="ld-queue">
          <div className="ld-queue__head">Preprocessor flag</div>
          <ul className="ld-queue__list">
            {CLAIMS.map((c, i) => (
              <li key={c.text}>
                <button
                  type="button"
                  className={`ld-qitem${i === index ? " is-active" : ""}${i < done ? " is-done" : ""}`}
                  onClick={() => {
                    setDriving(true);
                    setPressed(false);
                    setIndex(i);
                  }}
                >
                  <span className="ld-qitem__mark" aria-hidden>
                    {i < done ? "✓" : "○"}
                  </span>
                  <span className="ld-qitem__text">{c.text}</span>
                  {c.conflict ? (
                    <span className="ld-qitem__flag" aria-label="conflict">
                      ⚑
                    </span>
                  ) : null}
                </button>
              </li>
            ))}
          </ul>
          <div className="ld-queue__foot">
            <div className="ld-meter">
              <span style={{ width: `${pct}%` }} />
            </div>
            <span>
              {done} of {CLAIMS.length} confirmed
            </span>
          </div>
        </aside>

        <section className="ld-stage" key={index}>
          <div className="ld-stage__meta">
            <span className={`ld-tag ld-tag--${claim.type.replace(" ", "-")}`}>{claim.type}</span>
            <Pips level={claim.confidence} />
            <span className="ld-stage__from">
              {claim.source} · {claim.ref}
            </span>
          </div>

          {/* Claim, its conflict and its edges travel together so the slack
              left over by a short claim splits above and below them instead of
              pooling into one hole beneath. The evidence column opposite is
              taller than this one by construction — it holds a quote — so that
              slack always exists and only its placement is ours to choose. */}
          <div className="ld-stage__body">
            <p className="ld-claim">{claim.text}</p>

            {claim.conflict ? (
              <div className="ld-flag">
                <span aria-hidden>⚑</span>
                <div>
                  <b>Conflict</b>
                  <p>
                    {claim.conflict}. Atlas will not pick a winner — both stay until you decide.
                  </p>
                </div>
              </div>
            ) : null}

            <p className="ld-edges">
              <span>edges</span>
              {claim.relates}
            </p>
          </div>

          {/* Glyphs and keys are copied from the real review screen
              (ReviewPage.tsx §actions) rather than invented. A landing page
              that teaches the wrong shortcut is a small lie the product
              corrects in the first minute. */}
          <div className="ld-actions">
            <span className={`ld-btn ld-btn--primary${pressed ? " is-pressed" : ""}`}>
              ✓ Confirm <kbd>c</kbd>
            </span>
            <span className="ld-btn">
              ✎ Edit <kbd>e</kbd>
            </span>
            <span className="ld-btn">
              ✕ Reject <kbd>x</kbd>
            </span>
            <span className="ld-btn ld-btn--ghost">
              Add <kbd>a</kbd>
            </span>
          </div>
        </section>

        <aside className="ld-ev" key={`ev-${index}`}>
          <div className="ld-ev__head">Where it came from</div>
          <div className="ld-doc">
            <div className="ld-doc__head">
              <span className={`ld-src ld-src--${claim.source.toLowerCase()}`}>{claim.source}</span>
              <span className="ld-doc__ref">{claim.ref}</span>
            </div>
            <blockquote className="ld-quote">
              <MarkedQuote excerpt={claim.excerpt} mark={claim.mark} />
            </blockquote>
            <span className="ld-doc__open">Open in {claim.source} ↗</span>
          </div>
          <p className="ld-ev__note">
            Verbatim, never paraphrased. A claim that can't quote its source is rejected before it
            reaches you.
          </p>
        </aside>
      </div>
    </div>
  );
}

/* ── before / after ──────────────────────────────────────────────────────────
 *
 * The single hardest thing to convey in prose: what Atlas turns into what.
 * Left is what a feature's context actually looks like today; right is the
 * same information after extraction. Same facts, both columns.
 */
export function TransformDemo() {
  return (
    <div className="ld-transform">
      <div className="ld-col">
        <span className="ld-col__label">What you read today</span>
        <div className="ld-scatter">
          <article className="ld-raw">
            <header>
              <span className="ld-src ld-src--github">GitHub</span> PR #1231 · description
            </header>
            <p>
              Adds a `--pre` flag so search can shell out to a preprocessor. Still figuring out the
              filtering story, see thread below. Also fixes the unrelated flaky test in
              `tests/search.rs` while I was in here.
            </p>
          </article>
          <article className="ld-raw">
            <header>
              <span className="ld-src ld-src--github">GitHub</span> review · 34 comments
            </header>
            <p>
              “I think we should just run it on everything and let the user sort it out…” <br />
              “one thing though: we should skip anything binary…” <br />
              “+1” · “can we land this before Friday?” · “rebased”
            </p>
          </article>
          <article className="ld-raw">
            <header>
              <span className="ld-src ld-src--jira">Jira</span> SCRUM-14 · closed
            </header>
            <p>
              Acceptance: only invoke the preprocessor for paths that match `--pre-glob`. Unclear
              whether we want a repeatable flag or a comma list here.
            </p>
          </article>
          <span className="ld-scatter__fade" aria-hidden />
        </div>
        <p className="ld-col__foot">
          Three tabs, ~40 comments, two of which decide the feature. A morning of reading, and the
          contradiction is still invisible.
        </p>
      </div>

      <div className="ld-arrow" aria-hidden>
        <span className="ld-arrow__pill">Atlas</span>
        <span className="ld-arrow__line" />
      </div>

      <div className="ld-col">
        <span className="ld-col__label">What Atlas hands back</span>
        <div className="ld-yield">
          {CLAIMS.map((c) => (
            <article key={c.text} className={`ld-out${c.conflict ? " is-conflict" : ""}`}>
              <header>
                <span className={`ld-tag ld-tag--${c.type.replace(" ", "-")}`}>{c.type}</span>
                <span className="ld-out__src">
                  {c.source} · {c.ref}
                </span>
                {c.conflict ? <span className="ld-out__flag">⚑ conflict</span> : null}
              </header>
              <p>{c.text}</p>
              <blockquote>“{c.mark}”</blockquote>
            </article>
          ))}
        </div>
        <p className="ld-col__foot">
          Four typed claims, each quoting the line it came from — and the contradiction between two
          of them, surfaced rather than silently resolved.
        </p>
      </div>
    </div>
  );
}

/* ── act one: connect ────────────────────────────────────────────────────── */
export function ConnectDemo() {
  return (
    <div className="ld-panel">
      <div className="ld-panel__head">Sources</div>
      <div className="ld-conn">
        <div className="ld-conn__row">
          <span className="ld-src ld-src--github">GitHub</span>
          <div>
            <b>BurntSushi/ripgrep</b>
            <small>connected as you · read-only</small>
          </div>
          <span className="ld-ok">✓ scoped</span>
        </div>
        <div className="ld-conn__row">
          <span className="ld-src ld-src--jira">Jira</span>
          <div>
            <b>SCRUM</b>
            <small>connected as you · read-only</small>
          </div>
          <span className="ld-ok">✓ scoped</span>
        </div>
      </div>
      <div className="ld-scope">
        <span className="ld-scope__label">Pull for this feature</span>
        <div className="ld-scope__chips">
          <span className="ld-chip is-on">PR #1231</span>
          <span className="ld-chip is-on">epic SCRUM-14</span>
          <span className="ld-chip">+ add a target</span>
        </div>
        <p>
          Never a crawl. Atlas reads what you point it at, with your credential, and nothing else.
        </p>
      </div>
    </div>
  );
}

/* ── act two: extract ────────────────────────────────────────────────────── */
export function ExtractDemo() {
  return (
    <div className="ld-panel">
      <div className="ld-panel__head">
        Run · <b>Preprocessor flag</b>
        <span className="ld-run">reading</span>
      </div>
      <ol className="ld-log">
        <li>
          <span>fetched</span> PR #1231 · 34 comments, 2 review threads
        </li>
        <li>
          <span>fetched</span> SCRUM-14 · description + 6 comments
        </li>
        <li>
          <span>emitted</span> requirement <em>— quoting SCRUM-14</em>
        </li>
        <li>
          <span>emitted</span> decision <em>— quoting #1231 review</em>
        </li>
        <li className="is-flag">
          <span>flagged</span> conflict between the two <em>— not resolved</em>
        </li>
        <li>
          <span>dropped</span> 11 candidates with no quotable source
        </li>
      </ol>
      <p className="ld-panel__foot">
        Every claim is schema-validated with its source excerpt attached before it is allowed to be
        stored. There is no path into Atlas that skips that check.
      </p>
    </div>
  );
}

/* ── act three: confirm ──────────────────────────────────────────────────────
 *
 * The hero demo already shows the loop moving, so this one shows its *output*:
 * what a claim looks like after a person has acted on it, with their name on
 * it. That attribution is the whole point of the confirmation step — it is
 * what turns a draft into something another human can rely on.
 */
export function ConfirmDemo() {
  return (
    <div className="ld-panel">
      <div className="ld-panel__head">After the pass</div>
      <div className="ld-settled">
        <article className="ld-settled__row is-confirmed">
          <span aria-hidden>✓</span>
          <div>
            <p>The preprocessor must only run on files matching an explicit glob.</p>
            <small>confirmed by Priya · quoting SCRUM-14</small>
          </div>
        </article>
        <article className="ld-settled__row is-edited">
          <span aria-hidden>✎</span>
          <div>
            <p>Preprocessing must skip files detected as binary by the standard heuristic.</p>
            <small>edited by Priya · original text kept in the log</small>
          </div>
        </article>
        <article className="ld-settled__row is-rejected">
          <span aria-hidden>✕</span>
          <div>
            <p>Land the flag before Friday.</p>
            <small>rejected · scheduling chatter, not a requirement</small>
          </div>
        </article>
        <article className="ld-settled__row is-open">
          <span aria-hidden>⚑</span>
          <div>
            <p>The GitHub decision and the Jira requirement still contradict each other.</p>
            <small>left open on purpose · Atlas never picks a winner</small>
          </div>
        </article>
      </div>
      <div className="ld-keys">
        <kbd>j</kbd>/<kbd>k</kbd> move <kbd>c</kbd> confirm <kbd>e</kbd> edit <kbd>x</kbd> reject{" "}
        <kbd>a</kbd> add <kbd>o</kbd> open source <kbd>u</kbd> undo
      </div>
    </div>
  );
}
