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
 * ## Rebuilt 2026-08-22 against the screen it claims to be a picture of
 *
 * Live DOM stops a demo drifting on *colour*. It does nothing to stop it
 * drifting on *layout*, and it had: the review screen was rebuilt (one title
 * bar over a queue and a reflowing card stack, `ReviewPage.tsx` header), the
 * rail's one-item "CONNECT"/"REVIEW" group labels were deleted in favour of
 * icons, and an `About` destination was added — and this file still drew the
 * previous build of all three. A landing page showing a layout the product no
 * longer has is worse than one showing a still: the still at least dates
 * itself. So the frame below now mirrors the real screen structure for
 * structure:
 *
 *   ld-rail    Overview · About · Sources · Conflicts, glyph-led, no group
 *              labels over single items — `App.tsx` §rail
 *   ld-rvbar   the feature, what it was assembled from, progress, conflicts —
 *              `ReviewPage.tsx` §rv__bar
 *   ld-queue   three views, then claims under plain-English group headings
 *              ("What it must do" / "How it was decided" / "Unresolved"), which
 *              are `GROUPS` in `review.ts` verbatim
 *   ld-work    the card stack: the claim and its rulings, the disagreement, and
 *              opposite them the receipt and what else came out of that thread
 *
 * ## The four tabs each have to teach something
 *
 * The strip has always named the four claim types, and every tab used to open
 * the same picture with a different sentence in it — four screenshots of one
 * screenshot. A reader who clicks "Constraint" is asking what a constraint *is*
 * and why Atlas bothers typing it; showing them the same frame answers neither.
 *
 * So each claim now carries a `lens` (one sentence: what this type is, and what
 * about it is worth your attention) and a `spot` naming the region of the frame
 * that makes the point — the receipt for a requirement, the disagreement for a
 * decision, the rest of the thread for a constraint, the Unresolved group for
 * an open question. The named region gets `is-spot`. Four tabs, four different
 * arguments, one screen.
 *
 * The content is the ripgrep `--pre` flag feature from the validation set —
 * the same real example the rest of the page already cites, including the
 * genuine GitHub/Jira conflict the extraction agent found. Nothing here is a
 * capability Atlas doesn't have.
 *
 * Class names are `ld-` prefixed because the app's own `.claim`, `.actions`,
 * `.card` and `.badge` are global and these must not inherit from them by
 * accident.
 */

import { useEffect, useRef, useState } from "react";
import {
  IconAbout,
  IconConflict,
  IconOverview,
  IconPanel,
  IconSources,
} from "../icons";

type ClaimType = "requirement" | "decision" | "constraint" | "open question";

/** Which queue group a claim files under. The keys and labels are `GROUPS` in
 * `review.ts` — the demo groups its four claims exactly as the app would. */
type GroupKey = "what" | "how" | "open";

const GROUP_LABELS: Record<GroupKey, string> = {
  what: "What it must do",
  how: "How it was decided",
  open: "Unresolved",
};

/** The region of the frame that carries this claim type's argument. */
type Spot = "queue" | "conflict" | "evidence" | "siblings";

type Claim = {
  type: ClaimType;
  group: GroupKey;
  source: "GitHub" | "Jira";
  ref: string;
  /** What the source document is, said the way the app's evidence card says it. */
  refNote: string;
  text: string;
  excerpt: string;
  /* The substring of `excerpt` the extractor keyed on, marked in the quote the
   way the review screen marks it. Must appear verbatim in `excerpt`. */
  mark: string;
  confidence: 1 | 2 | 3;
  /** Index into `CLAIMS` of the claim this one contradicts, if any. Both sides
   * of a disagreement carry it, because the real screen flags both — a conflict
   * is a fact about a pair, not a mark on whichever side was extracted second. */
  conflictWith?: number;
  /** The `Related` card's line: what this claim rests on or bears on. */
  relates: string;
  /** One sentence: what this type is, ending at the thing worth looking at. */
  lens: string;
  spot: Spot;
};

const CLAIMS: Claim[] = [
  {
    type: "requirement",
    group: "what",
    source: "Jira",
    ref: "SCRUM-14",
    refNote: "description + 6 comments",
    text: "The preprocessor must only run on files matching an explicit glob.",
    excerpt:
      "Acceptance: only invoke the preprocessor for paths that match --pre-glob. Everything else goes down the normal search path.",
    mark: "only invoke the preprocessor for paths that match --pre-glob",
    confidence: 3,
    conflictWith: 1,
    relates: "constrains → the --pre flag",
    lens: "Something the feature must do. Atlas types a claim as a requirement only when a source says it outright — so it arrives with the sentence it came from, which is the card on the right.",
    spot: "evidence",
  },
  {
    type: "decision",
    group: "how",
    source: "GitHub",
    ref: "#1231",
    refNote: "34 comments, 2 review threads",
    text: "The preprocessor runs on every file, unmatched by any filter.",
    excerpt:
      "I think we should just run it on everything and let the user sort it out. A filter is one more flag nobody will remember.",
    mark: "just run it on everything",
    confidence: 2,
    conflictWith: 0,
    relates: "contradicts → the requirement extracted from SCRUM-14",
    lens: "A choice someone made, in a thread nobody re-reads. This one contradicts the ticket, and that is invisible until both are in the same place — so Atlas holds up both and picks neither.",
    spot: "conflict",
  },
  {
    type: "constraint",
    group: "what",
    source: "GitHub",
    ref: "#1231",
    refNote: "34 comments, 2 review threads",
    text: "Preprocessing must skip files detected as binary.",
    excerpt:
      "One thing though: we should skip anything binary. Running the preproc on a 2GB core dump is a footgun.",
    mark: "we should skip anything binary",
    confidence: 3,
    relates: "constrains → the --pre flag · raised during review of #1231",
    lens: "A limit someone mentioned in passing — one line, deep in a review thread, phrased as an aside. It is also the line that breaks the build. Here is what else that same thread was holding.",
    spot: "siblings",
  },
  {
    type: "open question",
    group: "open",
    source: "Jira",
    ref: "SCRUM-14",
    refNote: "description + 6 comments",
    text: "Can --pre-glob be repeated, or does it take one comma-separated list?",
    excerpt:
      "Unclear whether we want a repeatable --pre-glob or a comma list here. Needs a call before implementation.",
    mark: "Needs a call before implementation",
    confidence: 2,
    relates: "blocks → the requirement extracted from SCRUM-14",
    lens: "Something nobody decided. Atlas will not decide it for you — it lifts the question out of the thread and keeps it under Unresolved until a person rules on it.",
    spot: "queue",
  },
];

/** The claims Atlas drew from the same source document as this one — the app's
 * `siblingsOf`, over the demo's four claims rather than over a projection. */
const siblingsOf = (index: number) =>
  CLAIMS.map((claim, i) => ({ claim, i })).filter(
    ({ claim, i }) => i !== index && claim.ref === CLAIMS[index]!.ref,
  );

const STEP_MS = 3400;
const PRESS_AT = 2900;
/* How long a reader who clicked a claim is left alone before the loop resumes.
 Long enough to read the longest excerpt in the set twice over, which is the
 only thing this number has to be right about. */
const IDLE_MS = 9000;

/* The rail is the rest of the application, drawn so the demo reads as a
 screenshot of Atlas rather than of one panel inside it. Both features are
 real rows from the ripgrep validation set — the same discipline as the
 claims: nothing on this page is a screenshot of software that doesn't run. */
const RAIL_FEATURES: { title: string; claims: number; conflicts?: number }[] = [
  { title: "Preprocessor flag", claims: 4, conflicts: 2 },
  { title: "Max depth option", claims: 3 },
];

/** The rail's destinations, in the app's own order. `About` is the newest of
 * them and the reason this list is worth keeping honest: it is the screen the
 * confirmations accumulate into, so a rail without it shows a loop with no
 * output. */
const RAIL_NAV: { label: string; icon: typeof IconOverview; badge?: number }[] =
  [
    { label: "Overview", icon: IconOverview },
    { label: "About", icon: IconAbout },
    { label: "Sources", icon: IconSources },
    { label: "Conflicts", icon: IconConflict, badge: 1 },
  ];

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

/** A card, with the head treatment every card on the real screen wears. */
function Card({
  title,
  count,
  tone,
  spot,
  aux,
  end,
  children,
}: {
  title: string;
  count?: number;
  tone?: "paper";
  spot?: boolean;
  /** Context rather than argument — dropped on the narrowest layouts, where the
   * alternative is a frame taller than the screen it is being read on. */
  aux?: boolean;
  end?: React.ReactNode;
  children: React.ReactNode;
}) {
  const classes = ["ld-card", tone && `ld-card--${tone}`, aux && "ld-card--aux", spot && "is-spot"]
    .filter(Boolean)
    .join(" ");
  return (
    <article className={classes}>
      <div className="ld-card__head">
        <span className="ld-card__title">{title}</span>
        {count !== undefined && (
          <span className="ld-card__n">{count}</span>
        )}
        {end && <span className="ld-card__end">{end}</span>}
      </div>
      <div className="ld-card__body">{children}</div>
    </article>
  );
}

/* ── the hero demo ───────────────────────────────────────────────────────────
 *
 * Autoplays a confirmation pass and loops. It stops when off-screen, when the
 * reader prefers reduced motion, and once the reader takes the wheel — at that
 * point they are driving, and something that keeps moving under a cursor is a
 * bug, not a demo.
 *
 * Taking the wheel used to mean clicking a row in the demo's own queue, which
 * works but is invisible: nothing about an auto-advancing panel says "you may
 * touch this". So the four claims are also a tab strip above the frame — the
 * same affordance a product tour uses, where the tabs both label what you are
 * about to see and are obviously clickable. Auto-play moves the active tab with
 * it, so the strip doubles as the progress indicator it would otherwise need.
 *
 * A hold is either **timed or sticky**, and the difference is what the reader
 * meant by it. Clicking a claim means "wait, let me read this one" — so the
 * loop stops and starts itself again once they have plainly stopped reading
 * (`IDLE_MS`). Clicking the badge means "stop moving" — so it stays stopped
 * until they say otherwise. Collapsing the two, in either direction, gets one
 * of them wrong: a demo that resumes under a cursor is a bug, and a demo that
 * sits frozen for the next reader because someone clicked once is a waste of
 * the only thing on the page that moves.
 */
type Hold = "none" | "timed" | "sticky";

export function ReviewDemo() {
  const [index, setIndex] = useState(0);
  const [pressed, setPressed] = useState(false);
  const [hold, setHold] = useState<Hold>("none");
  const [inView, setInView] = useState(false);
  const frame = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const node = frame.current;
    if (!node) return;
    const io = new IntersectionObserver(
      ([entry]) => setInView(Boolean(entry?.isIntersecting)),
      {
        threshold: 0.25,
      },
    );
    io.observe(node);
    return () => io.disconnect();
  }, []);

  const calm =
    typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  const playing = inView && hold === "none" && !calm;

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

  /* The countdown back to auto-play. `index` is a dependency so that every
   further click restarts it — a reader clicking through all four claims is
   still reading, and should not have the loop start moving mid-sentence. */
  useEffect(() => {
    if (hold !== "timed") return;
    const wake = window.setTimeout(() => setHold("none"), IDLE_MS);
    return () => window.clearTimeout(wake);
  }, [hold, index]);

  const claim = CLAIMS[index]!;
  const other =
    claim.conflictWith === undefined ? null : CLAIMS[claim.conflictWith]!;
  const siblings = siblingsOf(index);
  const done = index;
  const pct = Math.round((done / CLAIMS.length) * 100);

  /* One place decides what "the reader took over" means, so the tab strip and
   the in-frame queue can never disagree about it. */
  const goTo = (i: number) => {
    setHold("timed");
    setPressed(false);
    setIndex(((i % CLAIMS.length) + CLAIMS.length) % CLAIMS.length);
  };

  /* The queue, grouped the way the app groups it. Built from the same four
   claims rather than from a parallel list, so a claim can never appear on the
   stage and be missing from the list beside it. */
  const groups = (Object.keys(GROUP_LABELS) as GroupKey[])
    .map((key) => ({
      key,
      label: GROUP_LABELS[key],
      items: CLAIMS.map((c, i) => ({ claim: c, i })).filter(
        ({ claim: c }) => c.group === key,
      ),
    }))
    .filter((group) => group.items.length > 0);

  return (
    <div className="ld-shell" ref={frame}>
      <div
        className="ld-tabs"
        role="tablist"
        aria-label="Claims in this feature"
      >
        {CLAIMS.map((c, i) => (
          <button
            key={c.text}
            type="button"
            role="tab"
            aria-selected={i === index}
            className={`ld-tab${i === index ? " is-active" : ""}`}
            onClick={() => goTo(i)}
          >
            <span className={`ld-tab__glyph ld-tag--${c.type.replace(" ", "-")}`} aria-hidden />
            {c.type[0]!.toUpperCase() + c.type.slice(1)}
          </button>
        ))}
      </div>

      {/* What this tab is *for*. Without it the four tabs open four pictures of
          the same picture; with it each one names the part of the screen that
          answers the question the reader clicked the tab to ask. */}
      <p className="ld-lens" key={`lens-${index}`}>
        {claim.lens}
      </p>

      <div className="ld-frame">
        {/* Not window chrome pretending to be a browser: the address is the
            route the application really serves (`router.ts`), which is worth
            showing — every screen in Atlas has a URL you can send someone. The
            badge is the deliberate control: from playing it stops things for
            good, from stopped it starts them again now rather than after the
            countdown. */}
        <div className="ld-frame__bar">
          <span className="ld-dots" aria-hidden>
            <i />
            <i />
            <i />
          </span>
          <span className="ld-frame__url">
            <span>atlas.app</span>/p/ripgrep/f/preprocessor-flag
          </span>
          <button
            type="button"
            className="ld-frame__live"
            onClick={() => setHold((h) => (h === "none" ? "sticky" : "none"))}
            title={playing ? "Pause" : "Resume auto-play"}
          >
            {playing ? "auto-playing" : calm ? "paused" : "▸ resume"}
          </button>
        </div>

        {/* Everything below is one screenshot of the running application: its
            own left rail, then the review screen inside it. The rail is static
            by design — it is context for the panes that do move, and a second
            animated thing here would compete with the claim for the eye. */}
        <div className="ld-app">
          <nav className="ld-rail" aria-hidden>
            <span className="ld-rail__brand">
              <span className="rail__glyph" />
              Atlas
            </span>
            <span className="ld-rail__product">
              ripgrep
              <i>▾</i>
            </span>

            {RAIL_NAV.map(({ label, icon: Icon, badge }) => (
              <span key={label} className="ld-rail__nav">
                <Icon className="ld-rail__icon" />
                {label}
                {badge ? <em className="is-conflict">{badge}</em> : null}
              </span>
            ))}

            <span className="ld-rail__label">
              Features<b>2</b>
            </span>
            <span className="ld-rail__filter">
              ⌕ Filter features<kbd>⌘K</kbd>
            </span>
            {RAIL_FEATURES.map((f, i) => (
              <span
                key={f.title}
                className={`ld-rail__feat${i === 0 ? " is-active" : ""}`}
              >
                {f.title}
                {f.conflicts ? (
                  <em className="is-conflict">
                    {f.conflicts}
                  </em>
                ) : (
                  <em>{f.claims}</em>
                )}
              </span>
            ))}

            <span className="ld-rail__work">
              <span className="ld-rail__label">Work left</span>
              <span className="ld-rail__work-row">
                Reviewed
                <b>
                  {done} / {CLAIMS.length}
                </b>
              </span>
              <span className="ld-meter">
                <span style={{ width: `${pct}%` }} />
              </span>
            </span>
          </nav>

          <div className="ld-rv">
            {/* The screen's one heading, and the only sans heading on it —
                `ReviewPage.tsx` §rv__bar. The demo used to put the feature name
                in the window chrome instead, which is a place the application
                does not have. */}
            <div className="ld-rvbar">
              <span className="ld-rvbar__panel" aria-hidden>
                <IconPanel />
              </span>
              <span className="ld-rvbar__title">
                Preprocessor flag
              </span>
              <span className="ld-rvbar__from">
                <span className="ld-rvbar__from-label">
                  assembled from
                </span>
                <span className="ld-badge">gh</span>
                <span className="ld-badge">jr</span>
              </span>
              <span className="ld-rvbar__prog">
                <span className="ld-rvbar__prog-n">
                  <b>{done}</b>/{CLAIMS.length} reviewed
                </span>
                <span className="ld-meter">
                  <span style={{ width: `${pct}%` }} />
                </span>
              </span>
              <span className="ld-rvbar__conflicts">
                <span aria-hidden>⚠</span> 2 claims in 1
                conflict
              </span>
            </div>

            <div className="ld-review">
              <aside className="ld-queue">
                {/* Three views, not a filter menu — a menu hides its own state,
                    and "not everything" is exactly the state worth showing. */}
                <div className="ld-qviews" role="presentation">
                  <span className="ld-qview is-active">
                    Needs ruling
                    <b>{CLAIMS.length - done}</b>
                  </span>
                  <span className="ld-qview">
                    Conflicts<b>2</b>
                  </span>
                  <span className="ld-qview">
                    All<b>{CLAIMS.length}</b>
                  </span>
                </div>

                <div className="ld-queue__scroll">
                  {groups.map((group) => {
                    const left = group.items.filter(
                      ({ i }) =>
                        i >= done ||
                        CLAIMS[i]!.conflictWith !==
                          undefined,
                    ).length;
                    return (
                      <div
                        key={group.key}
                        className={`ld-qsection${
                          claim.spot === "queue" &&
                          group.key === claim.group
                            ? " is-spot"
                            : ""
                        }`}
                      >
                        <div className="ld-qgroup">
                          <span className="ld-qgroup__label">
                            {group.label}
                          </span>
                          <span
                            className={`ld-qgroup__n${left ? " is-open" : ""}`}
                          >
                            {left
                              ? `${left} left`
                              : "done"}
                          </span>
                        </div>
                        {group.items.map(
                          ({ claim: c, i }) => (
                            <button
                              key={c.text}
                              type="button"
                              className={`ld-qitem${i === index ? " is-active" : ""}${
                                i < done
                                  ? " is-done"
                                  : ""
                              }`}
                              onClick={() =>
                                goTo(i)
                              }
                            >
                              <span
                                className="ld-qitem__mark"
                                aria-hidden
                              >
                                {i < done
                                  ? "✓"
                                  : "○"}
                              </span>
                              <span className="ld-qitem__text">
                                {c.text}
                                {c.conflictWith !==
                                undefined ? (
                                  <span
                                    className="ld-qitem__flag"
                                    aria-label="in conflict"
                                  >
                                    {" "}
                                    ⚠
                                  </span>
                                ) : null}
                              </span>
                            </button>
                          ),
                        )}
                      </div>
                    );
                  })}

                  {/* Only once something is hidden. The app renders this on
                      `hidden > 0`; the demo rendered it unconditionally, so its
                      opening frame read "0 settled claims hidden". */}
                  {done > 0 && (
                    <span className="ld-qdone">
                      <span aria-hidden>▸</span> {done} settled{" "}
                      {done === 1 ? "claim" : "claims"} hidden
                      <span className="ld-qdone__show">show all</span>
                    </span>
                  )}
                </div>
              </aside>

              {/* The reflow. Claim and evidence are siblings in one grid, not
                  two fixed panes, so on a wide workspace they sit abreast — the
                  comparison the product is *for*. */}
              <div className="ld-work">
                <div className="ld-stack" key={index}>
                  <div className="ld-stackcol">
                    <Card
                      title="The claim"
                      end={
                        <>
                          <span
                            className={`ld-tag ld-tag--${claim.type.replace(" ", "-")}`}
                          >
                            {claim.type}
                          </span>
                          <Pips
                            level={claim.confidence}
                          />
                          <span className="ld-status">
                            ○ to review
                          </span>
                        </>
                      }
                    >
                      <p className="ld-claim">
                        {claim.text}
                      </p>
                      {/* Glyphs and keys are copied from the real review screen
                          (ReviewPage.tsx §ClaimCard) rather than invented. A
                          landing page that teaches the wrong shortcut is a small
                          lie the product corrects in the first minute. */}
                      <div className="ld-actions">
                        <span
                          className={`ld-btn ld-btn--primary${pressed ? " is-pressed" : ""}`}
                        >
                          ✓ Confirm <kbd>c</kbd>
                        </span>
                        <span className="ld-btn">
                          ✎ Edit <kbd>e</kbd>
                        </span>
                        <span className="ld-btn">
                          ✕ Reject <kbd>x</kbd>
                        </span>
                      </div>
                    </Card>

                    {other && (
                      /* `.ld-flag` is the disagreement, drawn as the app draws
                       it: both sides, both quotes, no winner. */
                      <div
                        className={`ld-flag${claim.spot === "conflict" ? " is-spot" : ""}`}
                      >
                        <div className="ld-flag__head">
                          <span aria-hidden>⚠</span>{" "}
                          Disagreement
                          <em>
                            neither side is picked
                          </em>
                        </div>
                        <div className="ld-flag__pair">
                          <div className="ld-flag__side is-this">
                            <span className="ld-flag__who">
                              this claim · {claim.source}
                            </span>
                            <p>{claim.text}</p>
                          </div>
                          <span className="ld-flag__vs">
                            vs
                          </span>
                          <div className="ld-flag__side">
                            <span className="ld-flag__who">
                              {other.type} · {other.source}
                            </span>
                            <p>{other.text}</p>
                          </div>
                        </div>
                        <p className="ld-flag__note">
                          Confirming one side does not
                          settle this. Both stay open
                          until a person rejects one
                          of them.
                        </p>
                      </div>
                    )}

                    <Card title="Related" count={1} aux>
                      <p className="ld-edges">
                        {claim.relates}
                      </p>
                    </Card>
                  </div>

                  <div className="ld-stackcol">
                    <Card
                      title="Where it came from"
                      tone="paper"
                      spot={claim.spot === "evidence"}
                    >
                      <div className="ld-doc">
                        <div className="ld-doc__head">
                          <span
                            className={`ld-src ld-src--${claim.source.toLowerCase()}`}
                          >
                            {claim.source ===
                            "GitHub"
                              ? "gh"
                              : "jr"}
                          </span>
                          <span className="ld-doc__ref">
                            {claim.ref}
                            <em>{claim.refNote}</em>
                          </span>
                          <span className="ld-doc__open">
                            ↗ open
                          </span>
                        </div>
                        <blockquote className="ld-quote">
                          <MarkedQuote
                            excerpt={claim.excerpt}
                            mark={claim.mark}
                          />
                        </blockquote>
                      </div>
                      <p className="ld-ev__note">
                        Every excerpt is literal text
                        from the source, never a
                        paraphrase. That is what makes a
                        claim checkable rather than
                        merely plausible.
                      </p>
                    </Card>

                    {siblings.length > 0 && (
                      <Card
                        title="Also from this source"
                        count={siblings.length}
                        aux
                        spot={claim.spot === "siblings"}
                      >
                        <ul className="ld-sibs">
                          {siblings.map(
                            ({ claim: c, i }) => (
                              <li key={c.text}>
                                <button
                                  type="button"
                                  onClick={() =>
                                    goTo(i)
                                  }
                                >
                                  <span
                                    className="ld-sibs__mark"
                                    aria-hidden
                                  >
                                    {i <
                                    done
                                      ? "✓"
                                      : "○"}
                                  </span>
                                  <span>
                                    {c.text}
                                  </span>
                                </button>
                              </li>
                            ),
                          )}
                        </ul>
                      </Card>
                    )}
                  </div>
                </div>

                {/* The real screen's shortcut hint, pinned to the foot of the
                    workspace. It earns its place twice: it is what the
                    application actually shows, and it says out loud that this is
                    a keyboard surface for someone doing forty of these in a
                    sitting — which is most of the difference between a review
                    tool and a form. */}
                <p className="ld-hints">
                  <span>
                    <kbd>j</kbd>/<kbd>k</kbd> move
                  </span>
                  <span>
                    <kbd>o</kbd> open source
                  </span>
                  <span>
                    <kbd>c</kbd> confirm
                  </span>
                  <span>
                    <kbd>e</kbd> edit
                  </span>
                  <span>
                    <kbd>x</kbd> reject
                  </span>
                  <span>
                    <kbd>a</kbd> add
                  </span>
                  <span>
                    <kbd>u</kbd> undo
                  </span>
                  <span className="ld-hints__end">
                    <kbd>[</kbd> hide list
                  </span>
                </p>
              </div>
            </div>
          </div>
        </div>
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
              <span className="ld-src ld-src--github">gh</span> PR
              #1231 · description
            </header>
            <p>
              Adds a `--pre` flag so search can shell out to a
              preprocessor. Still figuring out the filtering
              story, see thread below. Also fixes the unrelated
              flaky test in `tests/search.rs` while I was in here.
            </p>
          </article>
          <article className="ld-raw">
            <header>
              <span className="ld-src ld-src--github">gh</span>{" "}
              review · 34 comments
            </header>
            <p>
              “I think we should just run it on everything and let
              the user sort it out…” <br />
              “one thing though: we should skip anything binary…”{" "}
              <br />
              “+1” · “can we land this before Friday?” · “rebased”
            </p>
          </article>
          <article className="ld-raw">
            <header>
              <span className="ld-src ld-src--jira">jr</span>{" "}
              SCRUM-14 · closed
            </header>
            <p>
              Acceptance: only invoke the preprocessor for paths
              that match `--pre-glob`. Unclear whether we want a
              repeatable flag or a comma list here.
            </p>
          </article>
          <span className="ld-scatter__fade" aria-hidden />
        </div>
        <p className="ld-col__foot">
          Three tabs, ~40 comments, two of which decide the feature. A
          morning of reading, and the contradiction is still
          invisible.
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
            <article
              key={c.text}
              className={`ld-out${c.conflictWith !== undefined ? " is-conflict" : ""}`}
            >
              <header>
                <span
                  className={`ld-tag ld-tag--${c.type.replace(" ", "-")}`}
                >
                  {c.type}
                </span>
                <span className="ld-out__src">
                  {c.source} · {c.ref}
                </span>
                {c.conflictWith !== undefined ? (
                  <span className="ld-out__flag">
                    ⚠ conflict
                  </span>
                ) : null}
              </header>
              <p>{c.text}</p>
              <blockquote>“{c.mark}”</blockquote>
            </article>
          ))}
        </div>
        <p className="ld-col__foot">
          Four typed claims, each quoting the line it came from, plus
          the contradiction between two of them, surfaced rather than
          silently resolved.
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
          <span className="ld-src ld-src--github">gh</span>
          <div>
            <b>BurntSushi/ripgrep</b>
            <small>connected as you · read-only</small>
          </div>
          <span className="ld-ok">✓ scoped</span>
        </div>
        <div className="ld-conn__row">
          <span className="ld-src ld-src--jira">jr</span>
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
          Never a crawl. Atlas reads what you point it at, with your
          credential, and nothing else.
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
          <span>fetched</span> PR #1231 · 34 comments, 2 review
          threads
        </li>
        <li>
          <span>fetched</span> SCRUM-14 · description + 6 comments
        </li>
        <li>
          <span>emitted</span> requirement <em>from SCRUM-14</em>
        </li>
        <li>
          <span>emitted</span> decision <em>from the #1231 review</em>
        </li>
        <li className="is-flag">
          <span>flagged</span> conflict between the two{" "}
          <em>(not resolved)</em>
        </li>
        <li>
          <span>dropped</span> 11 candidates with no quotable source
        </li>
      </ol>
      <p className="ld-panel__foot">
        Every claim is schema-validated with its source excerpt attached
        before it is allowed to be stored. There is no path into Atlas
        that skips that check.
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
            <p>
              The preprocessor must only run on files matching an
              explicit glob.
            </p>
            <small>confirmed by Priya · quoting SCRUM-14</small>
          </div>
        </article>
        <article className="ld-settled__row is-edited">
          <span aria-hidden>✎</span>
          <div>
            <p>
              Preprocessing must skip files detected as binary by
              the standard heuristic.
            </p>
            <small>
              edited by Priya · original text kept in the log
            </small>
          </div>
        </article>
        <article className="ld-settled__row is-rejected">
          <span aria-hidden>✕</span>
          <div>
            <p>Land the flag before Friday.</p>
            <small>
              rejected · scheduling chatter, not a requirement
            </small>
          </div>
        </article>
        <article className="ld-settled__row is-open">
          <span aria-hidden>⚠</span>
          <div>
            <p>
              The GitHub decision and the Jira requirement still
              contradict each other.
            </p>
            <small>
              left open on purpose · Atlas never picks a winner
            </small>
          </div>
        </article>
      </div>
      <div className="ld-keys">
        <kbd>j</kbd>/<kbd>k</kbd> move <kbd>c</kbd> confirm <kbd>e</kbd>{" "}
        edit <kbd>x</kbd> reject <kbd>a</kbd> add <kbd>o</kbd> open
        source <kbd>u</kbd> undo
      </div>
    </div>
  );
}

/* ── act four: hand off ──────────────────────────────────────────────────────
 *
 * New 2026-08-22, and the reason the page needed a fourth act at all: until
 * `/p/{id}/about` and `GET /products/{id}/spec` shipped, confirming a claim
 * made it *disappear* into a settled list and the product had no output to show
 * — so the page honestly stopped at "confirm". It doesn't stop there now.
 *
 * Two halves, because the two halves are the argument. Left: the About page,
 * which is a projection over confirmed claims and therefore writes itself as
 * the reviewing happens. Right: the same assembly as Markdown, which is what a
 * coding agent is actually handed.
 *
 * The counts and the shape of the file are taken from the real export of the
 * ripgrep validation product (17 confirmed of 43, 6 open disagreements), not
 * invented. What is deliberately *not* claimed anywhere here is that the spec
 * makes an agent's output better — that measurement is Phase 2 and has not been
 * run, and a landing page is not the place to pre-announce a result.
 */
export function SpecDemo() {
  return (
    <div className="ld-spec">
      <div className="ld-spec__pane">
        <span className="ld-spec__label">
          The About page · writes itself
        </span>
        <div className="ld-panel ld-panel--flush">
          <div className="ld-about__head">
            <b>ripgrep</b>
            <span className="ld-about__btns">
              <span className="ld-btn">Copy as Markdown</span>
              <span className="ld-btn">Download</span>
            </span>
          </div>
          <p className="ld-about__note">
            Assembled from <b>17</b> confirmed claims, each shown
            with the source text it came from. <b>26</b> more are
            still awaiting review and are not included.
          </p>
          <div className="ld-about__feature">
            <span className="ld-about__feat-name">
              Preprocessor flag
            </span>
            <span className="ld-about__pending">
              2 awaiting review
            </span>
          </div>
          <span className="ld-about__group">Requirements</span>
          <p className="ld-about__claim">
            The preprocessor must only run on files matching an
            explicit glob.
          </p>
          <blockquote className="ld-about__ex">
            only invoke the preprocessor for paths that match
            --pre-glob
          </blockquote>
          <span className="ld-about__cite">
            <span className="ld-src ld-src--jira">jr</span> SCRUM-14 ↗
          </span>
          <span className="ld-about__group">Constraints</span>
          <p className="ld-about__claim">Preprocessing must skip files detected as binary.</p>
          <blockquote className="ld-about__ex">we should skip anything binary</blockquote>
          <span className="ld-about__cite">
            <span className="ld-src ld-src--github">gh</span> #1231 ↗
          </span>
        </div>
      </div>

      <div className="ld-spec__pane">
        <span className="ld-spec__label">
          The same thing, as a file
        </span>
        <pre className="ld-md">
          <code>
            <b># ripgrep</b>
            {"\n\n"}
            <i>
              17 confirmed claims. 26 more await review and are
              not included.
            </i>
            {"\n\n"}
            <b>## Preprocessor flag</b>
            {"\n\n"}
            <b>### Requirements</b>
            {"\n\n"}- The preprocessor must only run on files
            matching an explicit glob.
            {"\n  "}
            <i>
              “only invoke the preprocessor for paths that match
              --pre-glob”
            </i>
            {"\n  "}
            <i>— Jira SCRUM-14 · https://…/browse/SCRUM-14</i>
            {"\n\n"}
            <b>### Open disagreements</b>
            {"\n\n"}
            <em>
              1. Neither side has been rejected, so both stand.
              {"\n"}
              {"   "}A. The preprocessor must only run on files
              matching a glob.{"\n"}
              {"   "}B. The preprocessor runs on every file,
              unmatched by any filter.
            </em>
          </code>
        </pre>
      </div>
    </div>
  );
}
