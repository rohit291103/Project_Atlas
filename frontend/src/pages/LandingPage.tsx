/* The public front door.
 *
 * Rebuilt 2026-08-16 (structure), restyled 2026-08-16 (visual language).
 *
 * The first version made the argument entirely in prose: eleven paragraphs,
 * zero product. The second replaced the prose with live product surfaces, which
 * fixed the substance but kept the app's own dense, hairline, ink-only chrome —
 * correct for a review screen a PM sits in for twenty minutes, and far too
 * quiet for a page a stranger gives eight seconds. Marketing surfaces and work
 * surfaces want opposite things from the same design system: the app spends its
 * colour budget on status and conflict and nothing else; the page in front of it
 * is allowed one confident brand gesture, because that is the whole job.
 *
 * So this page now carries a landing-scoped gradient identity — magenta →
 * violet → the product's own interaction blue — declared on `.landing` and
 * therefore reaching nothing behind the sign-in wall. The ramp *ends* on
 * `--accent`, the exact colour the primary button in the app is: the marketing
 * gesture resolves into the product's real palette rather than promising a
 * different-looking application.
 *
 * The spine, in order:
 *   1. hero      — the promise, the two ways in, and what it reads
 *   2. demo      — the review screen, running, given the space to be the point
 *   3. strip     — why the gathering is the expensive part
 *   4. loop      — the shape of the thing, as a diagram
 *   5. three acts — connect / extract / confirm, each beside its own screen
 *   6. turn      — the same feature's context, raw and then extracted
 *   7. conflict  — the thing no single source tool can do
 *   8. trust     — the four refusals
 *
 * Discipline carried over from every version, unchanged and deliberate:
 * everything here is a claim Atlas can actually back. The worked example is the
 * `--pre` flag feature from the ripgrep validation set, whose cross-source
 * conflict the extraction agent genuinely found between a GitHub review comment
 * and a Jira ticket. No invented customers, no logo wall of companies that have
 * never heard of us, no metrics nobody measured — the strip of sources below
 * the hero occupies that slot instead, and labels the ones that aren't built
 * yet as exactly that. A landing page that overstates is a promise the product
 * has to break in the first minute.
 *
 * The demos remain live DOM built from the product's own tokens, so the page
 * and the app are literally the same piece of software.
 */

import {
  ConfirmDemo,
  ConnectDemo,
  ExtractDemo,
  ReviewDemo,
  TransformDemo,
} from "../components/landing/demos";
import { LoopDiagram } from "../components/landing/loop";
import { SourceMark } from "../components/landing/sourceMarks";
import { linkProps } from "../router";
import type { Route } from "../router";
import { THEME_LABELS, useTheme } from "../theme";

/* Live means "you can connect it today". Everything else is labelled as not
   built — the same honesty rule the rest of the page runs on, applied to the
   one strip most sites use to imply more than they have. */
const SOURCES: { name: string; live: boolean }[] = [
  { name: "GitHub", live: true },
  { name: "Jira", live: true },
  { name: "Linear", live: false },
  { name: "Notion", live: false },
  { name: "Slack", live: false },
  { name: "Confluence", live: false },
];

export function LandingPage({
  navigate,
  signedInAs,
}: {
  navigate: (route: Route, replace?: boolean) => void;
  signedInAs: string | null;
}) {
  const [theme, cycleTheme] = useTheme();
  const cta: Route = signedInAs ? { name: "products" } : { name: "signin" };

  return (
    <div className="landing">
      {/* Nav. Brand and section links sit together on the left, the ways in on
          the right — the arrangement every developer-tool front door converges
          on, and the one that reads as navigation rather than as a second row
          of buttons competing with the hero's. */}
      <header className="landing__nav">
        <div className="landing__nav-left">
          <a className="landing__brand" {...linkProps({ name: "home" }, navigate)}>
            <span className="rail__glyph" aria-hidden />
            Atlas
          </a>
          <nav className="landing__nav-links">
            <a href="#demo">Demo</a>
            <a href="#loop">The loop</a>
            <a href="#how">How it works</a>
            <a href="#conflicts">Conflicts</a>
            <a href="#trust">Trust</a>
          </nav>
        </div>
        <div className="landing__nav-right">
          <button
            type="button"
            className="link-button landing__theme"
            onClick={cycleTheme}
            title={THEME_LABELS[theme]}
            aria-label={THEME_LABELS[theme]}
          >
            {theme === "dark" ? "☾" : theme === "light" ? "☀" : "◐"}
          </button>
          <a className="action action--brand action--sm" {...linkProps(cta, navigate)}>
            {signedInAs ? `Open Atlas as ${signedInAs}` : "Sign in"}
          </a>
        </div>
      </header>

      {/* Hero. Everything down to the terminal is one frame — `.hero__fold` is
          sized to the viewport, so a stranger sees the promise, both doors in
          and the CLI without scrolling. It buys that vertically by spending
          horizontally: the headline sets on two full-width lines rather than
          four short ones. The ambient gradient behind it lives in CSS
          (`.hero::before`) so it can be tuned per theme without touching the
          markup. */}
      <section className="hero">
        <div className="hero__fold">
          <p className="hero__eyebrow">
            <span className="hero__eyebrow-dot" aria-hidden />
            Context-to-spec engine
          </p>
          {/* Two clauses, one line each — the setup in ink, the turn in the
              brand ramp. Both are set `nowrap` above the mobile breakpoint, so
              the type scales with the viewport instead of the line breaking at
              an arbitrary word. */}
          <h1 className="hero__title">
            <span className="hero__title-line">Your team already decided this.</span>
            <span className="hero__title-line hero__title-grad">
              It's just scattered across six tools.
            </span>
          </h1>
          <p className="hero__lede">
            Atlas pulls every decision behind one feature out of the pull requests and tickets it's
            buried in, quoted exactly and confirmed by you.
          </p>
          <div className="hero__actions">
            <a className="action action--brand action--lg" {...linkProps(cta, navigate)}>
              {signedInAs ? "Open Atlas" : "Start with one feature"}
            </a>
            <a className="action action--lg" href="#demo">
              See it running
            </a>
          </div>

          {/* The engineer's door, next to the PM's. Both are real: the CLI is a
              first-class read path in the architecture, not a legacy shim, and
              these are the actual commands (`atlas ingest`, `atlas review`). */}
          <div className="hero__term">
            <span className="hero__term-label">Or start in your terminal</span>
            <div className="hero__term-box">
              <code>
                <span className="hero__term-prompt">$</span> atlas ingest BurntSushi/ripgrep 1231
              </code>
              <code className="is-dim">
                <span className="hero__term-prompt">$</span> atlas review &lt;feature-scope&gt;
              </code>
            </div>
          </div>
        </div>

        {/* The strip moves, for the reason a logo wall usually doesn't need to:
            ours has six items where a customer wall has twenty, and six static
            names read as "that's all?" while six in motion read as a list
            continuing past the edge. The track is rendered twice and translated
            by exactly half its width, which is what makes the loop seamless —
            the second copy is `aria-hidden` so a screen reader hears the six
            sources once, not twelve times. */}
        <div className="hero__sources">
          <span className="hero__sources-label">Reads what your team already writes</span>
          <div className="marquee">
            <div className="marquee__track">
              {[0, 1].map((copy) => (
                <ul key={copy} aria-hidden={copy === 1 ? true : undefined}>
                  {SOURCES.map((s) => (
                    <li key={s.name} className={s.live ? "is-live" : "is-planned"}>
                      <SourceMark name={s.name} />
                      {s.name}
                      {s.live ? null : <em>not built yet</em>}
                    </li>
                  ))}
                </ul>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* The demo, promoted. It used to sit in the hero's shadow with a
          footnote; it is the strongest thing on the page, so it gets a title,
          a lit frame and the full width. */}
      <section className="showcase" id="demo">
        <span className="pill">The review loop</span>
        <h2 className="display">Twenty minutes of reading, already read</h2>
        <p className="display__sub">
          The actual review screen, running. Claims and quotes come from the ripgrep{" "}
          <code>--pre</code> feature in our validation set, including the GitHub/Jira contradiction
          the extraction agent really found.
        </p>
        <div className="showcase__frame">
          <ReviewDemo />
        </div>
        <p className="showcase__note">
          It plays itself, or pick a claim above and drive. Auto-play stops the moment you do, and
          the badge in the title bar starts it again.
        </p>
      </section>

      <section className="strip">
        <div className="strip__item">
          <span className="strip__n">1</span>
          <div>
            <h3>Coding agents are faster than context</h3>
            <p>
              An agent can implement a feature in minutes. Assembling the context it needs to
              implement the <em>right</em> feature still takes a person a morning of reading.
            </p>
          </div>
        </div>
        <div className="strip__item">
          <span className="strip__n">2</span>
          <div>
            <h3>The answer already exists, in six places</h3>
            <p>
              The decision is in a review comment. The constraint is in a ticket nobody reopened.
              The reason both were chosen is in neither.
            </p>
          </div>
        </div>
        <div className="strip__item">
          <span className="strip__n">3</span>
          <div>
            <h3>So the work is gathering, not writing</h3>
            <p>
              Atlas does the gathering and the quoting. You do the deciding, which is the part that
              actually needs judgement.
            </p>
          </div>
        </div>
      </section>

      {/* The shape of the product, as a picture. See loop.tsx for why the
          fourth node is "hand off" and not "Atlas writes your spec". */}
      <section className="loop" id="loop">
        <span className="pill">Continuous context</span>
        <h2 className="display">Atlas runs the loop your feature context goes round</h2>
        <p className="display__sub">
          Not an importer you run once. A cycle a feature goes round, and the work that comes out
          of it is what starts the next pass.
        </p>
        <LoopDiagram />
      </section>

      {/* Three acts. Each is copy beside the screen it describes, alternating
          sides. The headings are questions on purpose: they are the questions a
          PM actually arrives with, and answering one is a better claim than
          naming a feature. */}
      <section className="how" id="how">
        <span className="pill">How it works</span>
        <h2 className="display">Three steps, about twenty minutes</h2>

        <div className="act">
          <div className="act__copy">
            <span className="act__step">Connect</span>
            <h3>What exactly is Atlas allowed to read?</h3>
            <p>
              Connect a GitHub repo and a Jira project with your own read credential. Atlas
              authenticates as you, so it can never reach a repo you couldn't open yourself.
            </p>
            <p>
              Then name the target: one pull request, one epic, one label. Every pull is deliberate
              and bounded. Atlas never crawls an org looking for something interesting.
            </p>
            <p className="act__note">
              Credentials are encrypted at rest with a key held outside the database, are returned
              by no endpoint, appear in no log line, and can be deleted outright.
            </p>
          </div>
          <div className="act__demo">
            <ConnectDemo />
          </div>
        </div>

        <div className="act act--flip">
          <div className="act__copy">
            <span className="act__step">Extract</span>
            <h3>Where did this claim actually come from?</h3>
            <p>
              An agent reads the thread and emits typed claims: goals, requirements, decisions,
              constraints, open questions. Every one carries the literal sentence it came from and a
              link back to it.
            </p>
            <p>
              Candidates that can't quote a source don't get softened into a paraphrase. They get
              dropped before you ever see them.
            </p>
            <p className="act__note">
              A claim with no source is structurally impossible here, not merely discouraged. The
              schema has nowhere to put one.
            </p>
          </div>
          <div className="act__demo">
            <ExtractDemo />
          </div>
        </div>

        <div className="act">
          <div className="act__copy">
            <span className="act__step">Confirm</span>
            <h3>Who decided this was true?</h3>
            <p>
              You see one claim, its evidence beside it, and four choices: confirm, edit, reject, or
              add something the tools never recorded. Confirming moves you to the next one. The
              whole loop is keyboard-first.
            </p>
            <p>
              What comes out the other side isn't an AI summary. It's a set of statements a named
              person vouched for, each still pointing at the sentence underneath it.
            </p>
            <p className="act__note">
              Nothing extracted counts as true until a person has said so, and edits keep the
              original text in the log.
            </p>
          </div>
          <div className="act__demo">
            <ConfirmDemo />
          </div>
        </div>
      </section>

      {/* The transformation. The one thing prose could never carry: same
          feature, same facts, left as you read it today and right as Atlas
          returns it. */}
      <section className="turn" id="turn">
        <div className="turn__intro">
          <span className="pill">Before / after</span>
          <h2 className="display">One feature. Same facts. Half a morning back.</h2>
          <p className="display__sub">
            Nothing on the right was invented. Every claim is a sentence someone already wrote,
            typed and quoted. The work Atlas removes is the reading, not the deciding.
          </p>
        </div>
        <TransformDemo />
      </section>

      <section className="conflict-demo" id="conflicts">
        <div className="conflict-demo__copy">
          <span className="act__step">Cross-source</span>
          <h2 className="display display--left">The part no single tool can do</h2>
          <p>
            One source contradicting another is invisible when you read them one at a time, and it
            is the most expensive thing to discover late. Atlas ingests a feature's sources into one
            place, so it can hold two claims up against each other and show you both, with both
            quotes.
          </p>
          <p className="conflict-demo__note">
            Below: a real conflict Atlas found between a GitHub review comment and a Jira ticket on
            the same feature. Neither document mentions the other.
          </p>
        </div>

        <div className="conflict-demo__card">
          <div className="conflict-demo__head">
            <span className="badge">conflict</span>
            <span>Preprocessor flag · assembled from GitHub + Jira</span>
          </div>
          <div className="conflict-demo__pair">
            <div className="conflict-demo__side">
              <span className="tag">decision · GitHub</span>
              <p>The preprocessor should run on every file, unmatched by any filter.</p>
              <blockquote className="conflict-demo__quote">
                “I think we should just run it on everything and let the user sort it out.”
              </blockquote>
            </div>
            <span className="conflict-demo__vs">vs</span>
            <div className="conflict-demo__side">
              <span className="tag">requirement · Jira</span>
              <p>The preprocessor must only run on files matching an explicit glob.</p>
              <blockquote className="conflict-demo__quote">
                “Only invoke the preprocessor for paths that match --pre-glob.”
              </blockquote>
            </div>
          </div>
        </div>
      </section>

      {/* The refusals, given the weight of a statement rather than a list in
          the page's margin. Four things a tool that reads your whole backlog
          could do and this one structurally will not. */}
      <section className="trust" id="trust">
        <div className="trust__card">
          <h2 className="display">
            It reads everything you point it at.
            <span className="hero__title-grad"> It writes nothing back.</span>
          </h2>
          <ul className="trust__list">
            <li>
              <strong>Never writes back.</strong> No comment, no ticket, no status change. Atlas is
              read-only into every tool it touches, permanently.
            </li>
            <li>
              <strong>Never paraphrases evidence.</strong> Every claim quotes the source verbatim
              and links to it. If you can't check it, it shouldn't have been extracted.
            </li>
            <li>
              <strong>Never decides for you.</strong> Extraction produces a draft. A claim is
              unconfirmed until a named person confirms it, and their name stays on it.
            </li>
            <li>
              <strong>Never sees more than you do.</strong> It uses your credential, with your
              permissions. Credentials are encrypted at rest and can be deleted outright.
            </li>
          </ul>
        </div>
      </section>

      <section className="closer">
        <h2>Start with one feature.</h2>
        <p>Connect two sources, review what comes out, and decide if it saved you the morning.</p>
        <a className="action action--brand action--lg" {...linkProps(cta, navigate)}>
          {signedInAs ? "Open Atlas" : "Start with one feature"}
        </a>
        <p className="closer__foot">
          Read-only into every source. Nothing is written back to GitHub or Jira, not in this
          version and not in any planned one.
        </p>
      </section>

      <footer className="landing__foot">
        <span>Atlas · context-to-spec engine</span>
        <span>Read-only · provenance-linked · human-confirmed</span>
      </footer>
    </div>
  );
}
