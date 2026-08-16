/* The entry surface, on its own route.
 *
 * Phase 1 auth is a shared passphrase plus the reviewer's name. The name is not
 * a display preference: it becomes the `actor` on every event that person
 * writes, so the audit trail names a real human rather than "user"
 * (docs/decisions/2026-08-11-api-frontend-module-boundary.md §4). That is why
 * the name field is first, explains what it is *for*, and why someone typing
 * "test" here has quietly broken the record — this is the only moment to say so.
 *
 * Restyled 2026-08-16 into the split every developer-tool sign-in now uses: a
 * dark brand panel stating what the product is, and a form column doing one
 * job. What did *not* change is why the left panel exists at all — it carries
 * the three promises that govern what happens after sign-in (read-only,
 * provenance, draft-not-fact). Someone about to hand a tool their GitHub token
 * should be told what it will and will not do *before* they do it, not in a
 * settings page afterwards. The restyle compressed them to a line each; it did
 * not drop them.
 *
 * Two things the reference layout wanted and Atlas will not fake: an OAuth row
 * (there is no Google or GitHub sign-in — the only credential is the shared
 * passphrase, and buttons that don't work are worse than buttons that aren't
 * there), and a customer logo wall. The bottom strip lists *sources* instead,
 * with the four unbuilt ones labelled as unbuilt — the same rule the landing
 * page runs on.
 */

import { useState } from "react";
import { linkProps } from "../router";
import type { Route } from "../router";
import { THEME_LABELS, useTheme } from "../theme";

const SOURCES: { name: string; live: boolean }[] = [
  { name: "GitHub", live: true },
  { name: "Jira", live: true },
  { name: "Linear", live: false },
  { name: "Notion", live: false },
  { name: "Slack", live: false },
];

const PROMISES: { title: string; body: string }[] = [
  {
    title: "It only ever reads",
    body: "No comment, no ticket, no status change — in this version or any planned one.",
  },
  {
    title: "Every claim quotes its source",
    body: "Verbatim, with a link. Nothing is paraphrased into something you can't go and check.",
  },
  {
    title: "Nothing is true until you say so",
    body: "Extraction is a draft. You confirm, edit or reject — and your name stays on the call.",
  },
];

export function SignInPage({
  onSignIn,
  error,
  navigate,
}: {
  onSignIn: (passphrase: string, name: string) => void;
  error: string | null;
  navigate: (route: Route, replace?: boolean) => void;
}) {
  const [passphrase, setPassphrase] = useState("");
  const [name, setName] = useState("");
  const [theme, cycleTheme] = useTheme();

  return (
    <div className="entry">
      <button
        type="button"
        className="entry__theme"
        onClick={cycleTheme}
        title={THEME_LABELS[theme]}
        aria-label={THEME_LABELS[theme]}
      >
        {theme === "dark" ? "☾" : theme === "light" ? "☀" : "◐"}
      </button>

      <div className="entry__grid">
        {/* The brand panel. Says what the thing is, promises what it won't do,
            and names what it reads — in that order, because that is the order
            the questions arrive in. */}
        <aside className="entry__panel">
          <a className="entry__panel-brand" {...linkProps({ name: "home" }, navigate)}>
            <span className="rail__glyph" aria-hidden />
            Atlas
          </a>

          <div className="entry__panel-body">
            <h1 className="entry__panel-title">The feature context loop</h1>
            <p className="entry__panel-sub">
              Everything your team already decided, gathered from the tools it's buried in.
              <br />
              Connect. Extract. Confirm.
            </p>

            <ul className="entry__promises">
              {PROMISES.map((promise) => (
                <li key={promise.title}>
                  <span className="entry__promise-mark" aria-hidden />
                  <div>
                    <h2>{promise.title}</h2>
                    <p>{promise.body}</p>
                  </div>
                </li>
              ))}
            </ul>
          </div>

          <div className="entry__sources">
            <span className="entry__sources-label">Reads</span>
            <ul>
              {SOURCES.map((source) => (
                <li key={source.name} className={source.live ? "is-live" : "is-planned"}>
                  {source.name}
                </li>
              ))}
            </ul>
          </div>
        </aside>

        <div className="entry__form-side">
          <form
            className="entry__card"
            onSubmit={(event) => {
              event.preventDefault();
              onSignIn(passphrase, name.trim());
            }}
          >
            <h1>Sign in to Atlas</h1>
            <p className="entry__lede">Your name goes on every decision you make here.</p>

            <label htmlFor="name">
              Your name
              <input
                id="name"
                value={name}
                autoComplete="name"
                autoFocus
                placeholder="Priya Raman"
                onChange={(event) => setName(event.target.value)}
              />
            </label>
            <p className="entry__note">
              Recorded on every decision you make, so anyone reading this feature later can see who
              confirmed what. Use the name you'd want on that record.
            </p>

            <label htmlFor="passphrase">
              Passphrase
              <input
                id="passphrase"
                type="password"
                value={passphrase}
                autoComplete="current-password"
                onChange={(event) => setPassphrase(event.target.value)}
              />
            </label>

            {error && <div className="notice notice--error">{error}</div>}

            <button
              type="submit"
              className="action action--brand action--lg entry__submit"
              disabled={!passphrase || !name.trim()}
            >
              Sign in
            </button>

            <p className="entry__foot">
              Access is granted per workspace. If your name isn't seated yet, Atlas will say so
              rather than letting you in and refusing everything you try.
            </p>

            <p className="entry__switch">
              New here?{" "}
              <a {...linkProps({ name: "home" }, navigate)}>See how Atlas works →</a>
            </p>
          </form>
        </div>
      </div>
    </div>
  );
}
