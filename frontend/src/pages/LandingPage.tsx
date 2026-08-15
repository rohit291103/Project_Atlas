/* The public front door.
 *
 * Rebuilt 2026-08-16. The previous version made the argument entirely in prose:
 * eleven paragraphs, zero product. It read as a manifesto for a thing that
 * might not be built yet — which is the opposite of the impression a working
 * extraction pipeline should leave. The rebuild leads with the artifact and
 * lets the copy annotate it, because the strongest claim Atlas can make is
 * simply showing what it hands back.
 *
 * The spine, in order:
 *   1. hero    — the promise, then immediately the review screen, running
 *   2. before/after — the same feature's context, raw and then extracted
 *   3. problem — why the gathering is the expensive part
 *   4. three acts — connect / extract / confirm, each beside its own screen
 *   5. conflict — the thing no single source tool can do
 *   6. principles — the four refusals
 *
 * Discipline carried over from the first version, unchanged and deliberate:
 * everything here is a claim Atlas can actually back. The worked example is
 * the `--pre` flag feature from the ripgrep validation set, whose cross-source
 * conflict the extraction agent genuinely found between a GitHub review
 * comment and a Jira ticket. No invented customers, no logo wall, no metrics
 * nobody measured. A landing page that overstates is a promise the product has
 * to break in the first minute.
 *
 * The visual language is the product's own (docs/ux/design-system-baseline-v1)
 * and the demos are live DOM built from the same tokens — so the marketing
 * page and the app are literally the same piece of software, which is itself
 * the argument.
 */

import {
  ConfirmDemo,
  ConnectDemo,
  ExtractDemo,
  ReviewDemo,
  TransformDemo,
} from "../components/landing/demos";
import { linkProps } from "../router";
import type { Route } from "../router";
import { THEME_LABELS, useTheme } from "../theme";

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
      <header className="landing__nav">
        <a className="landing__brand" {...linkProps({ name: "home" }, navigate)}>
          <span className="rail__glyph" aria-hidden />
          Atlas
        </a>
        <nav className="landing__nav-links">
          <a href="#demo">Demo</a>
          <a href="#how">How it works</a>
          <a href="#conflicts">Conflicts</a>
          <a href="#principles">Principles</a>
          <button
            type="button"
            className="link-button"
            onClick={cycleTheme}
            title={THEME_LABELS[theme]}
            aria-label={THEME_LABELS[theme]}
          >
            {theme === "dark" ? "☾" : theme === "light" ? "☀" : "◐"}
          </button>
          <a className="action action--primary action--sm" {...linkProps(cta, navigate)}>
            {signedInAs ? `Open Atlas as ${signedInAs}` : "Sign in"}
          </a>
        </nav>
      </header>

      {/* Hero. The headline states the problem in the reader's own words; the
          demo underneath is the answer, and it starts before they scroll. */}
      <section className="hero">
        <p className="hero__eyebrow">Context-to-spec engine</p>
        <h1 className="hero__title">
          Your team already decided this.
          <span className="hero__title-dim"> It's just scattered across six tools.</span>
        </h1>
        {/* Deliberately short. The demo directly below shows the provenance, the
            confirmation step and the queue — restating them here costs two lines
            of height and pushes the thing that proves them under the fold. */}
        <p className="hero__lede">
          Atlas pulls every decision behind one feature out of the pull requests and tickets it's
          buried in — quoted exactly, confirmed by you.
        </p>
        <div className="hero__actions">
          <a className="action action--primary" {...linkProps(cta, navigate)}>
            {signedInAs ? "Open Atlas" : "Start with one feature"}
          </a>
          <a className="action" href="#how">
            See how it works
          </a>
        </div>
      </section>

      {/* The nav's "Demo" link targets this section, not the hero above it — the
          demo is the product, and an anchor that lands on the headline reads as
          a dead link to anyone already at the top of the page. */}
      <section className="stage-wrap" id="demo">
        <ReviewDemo />
        <p className="stage-wrap__note">
          The actual review screen, running. Claims and quotes are from the ripgrep{" "}
          <code>--pre</code> feature in our validation set — including the GitHub/Jira contradiction
          the extraction agent really found. Click any claim to take over.
        </p>
      </section>

      {/* The transformation. The one thing prose could never carry: same
          feature, same facts, left as you read it today and right as Atlas
          returns it. */}
      <section className="turn" id="turn">
        <div className="turn__intro">
          <h2 className="section__title">One feature. Same facts. Half a morning back.</h2>
          <p>
            Nothing on the right was invented — every claim is a sentence someone already wrote,
            typed and quoted. The work Atlas removes is the reading, not the deciding.
          </p>
        </div>
        <TransformDemo />
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
              Atlas does the gathering and the quoting. You do the deciding — which is the part that
              actually needs judgement.
            </p>
          </div>
        </div>
      </section>

      {/* Three acts. Each one is copy beside the screen it describes, rather
          than three cards of text claiming things happen. */}
      <section className="how" id="how">
        <h2 className="section__title how__title">Three steps, about twenty minutes</h2>

        <div className="act">
          <div className="act__copy">
            <span className="act__step">Step one · Connect</span>
            <h3>Point it at one feature</h3>
            <p>
              Connect a GitHub repo and a Jira project with your own read credential. Atlas
              authenticates as you, so it can never reach a repo you couldn't open yourself.
            </p>
            <p>
              Then name the target: one pull request, one epic, one label. Every pull is deliberate
              and bounded — Atlas never crawls an org looking for something interesting.
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
            <span className="act__step">Step two · Extract</span>
            <h3>Claims, each with its receipt</h3>
            <p>
              An agent reads the thread and emits typed claims — goals, requirements, decisions,
              constraints, open questions. Every one carries the literal sentence it came from and a
              link back to it.
            </p>
            <p>
              Candidates that can't quote a source don't get softened into a paraphrase. They get
              dropped before you ever see them.
            </p>
            <p className="act__note">
              A claim with no source is structurally impossible here, not merely discouraged — the
              schema has nowhere to put one.
            </p>
          </div>
          <div className="act__demo">
            <ExtractDemo />
          </div>
        </div>

        <div className="act">
          <div className="act__copy">
            <span className="act__step">Step three · Confirm</span>
            <h3>One claim at a time, and your name on it</h3>
            <p>
              You see one claim, its evidence beside it, and four choices: confirm, edit, reject, or
              add something the tools never recorded. Confirming moves you to the next one. The
              whole loop is keyboard-first.
            </p>
            <p>
              What comes out the other side isn't an AI summary — it's a set of statements a named
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

      <section className="conflict-demo" id="conflicts">
        <div className="conflict-demo__copy">
          <h2 className="section__title">The part no single tool can do</h2>
          <p>
            One source contradicting another is invisible when you read them one at a time — and it
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

      <section className="principles" id="principles">
        <h2 className="section__title">What it will not do</h2>
        <ul className="principles__list">
          <li>
            <strong>It never writes back.</strong> No comment, no ticket, no status change. Atlas is
            read-only into every tool it touches, permanently.
          </li>
          <li>
            <strong>It never paraphrases evidence.</strong> Every claim quotes the source verbatim
            and links to it. If you can't check it, it shouldn't have been extracted.
          </li>
          <li>
            <strong>It never decides for you.</strong> Extraction produces a draft. A claim is
            unconfirmed until a named person confirms it, and their name stays on it.
          </li>
          <li>
            <strong>It never sees more than you do.</strong> It uses your credential, with your
            permissions. Credentials are encrypted at rest and can be deleted outright.
          </li>
        </ul>
      </section>

      <section className="closer">
        <h2>Start with one feature.</h2>
        <p>Connect two sources, review what comes out, and decide if it saved you the morning.</p>
        <a className="action action--primary" {...linkProps(cta, navigate)}>
          {signedInAs ? "Open Atlas" : "Start with one feature"}
        </a>
        <p className="closer__foot">
          Read-only into every source. Nothing is written back to GitHub or Jira — not in this
          version, not in any planned one.
        </p>
      </section>

      <footer className="landing__foot">
        <span>Atlas — context-to-spec engine</span>
        <span>Read-only · provenance-linked · human-confirmed</span>
      </footer>
    </div>
  );
}
