/* The entry surface, on its own route.
 *
 * Phase 1 auth is a shared passphrase plus the reviewer's name. The name is not
 * a display preference: it becomes the `actor` on every event that person
 * writes, so the audit trail names a real human rather than "user"
 * (docs/decisions/2026-08-11-api-frontend-module-boundary.md §4). That is why
 * the name field is first, explains what it is *for*, and why someone typing
 * "test" here has quietly broken the record — this is the only moment to say so.
 *
 * The split layout carries a second job: the right panel states the three
 * promises that govern what happens after sign-in (read-only, provenance,
 * draft-not-fact). Someone about to hand a tool their GitHub token should be
 * told what it will and will not do *before* they do it, not in a settings page
 * afterwards.
 */

import { useState } from "react";
import { linkProps } from "../router";
import type { Route } from "../router";

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

  return (
    <div className="entry">
      <div className="entry__form-side">
        <a className="landing__brand" {...linkProps({ name: "home" }, navigate)}>
          <span className="rail__glyph" aria-hidden />
          Atlas
        </a>

        <form
          className="entry__card"
          onSubmit={(event) => {
            event.preventDefault();
            onSignIn(passphrase, name.trim());
          }}
        >
          <h1>Sign in</h1>
          <p className="entry__lede">
            Everything your team already wrote about a feature, gathered in one place — so you can
            decide what is actually true.
          </p>

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
            className="action action--primary"
            disabled={!passphrase || !name.trim()}
          >
            Sign in
          </button>

          <p className="entry__foot">
            Access is granted per workspace. If your name isn't seated yet, Atlas will say so rather
            than letting you in and refusing everything you try.
          </p>
        </form>
      </div>

      <aside className="entry__promise-side">
        <ul className="entry__promises">
          <li>
            <span className="entry__promise-mark" aria-hidden />
            <div>
              <h2>It only ever reads</h2>
              <p>
                No comment, no ticket, no status change — in this version or any planned one. Your
                source tools look exactly the same after Atlas has read them.
              </p>
            </div>
          </li>
          <li>
            <span className="entry__promise-mark" aria-hidden />
            <div>
              <h2>Every claim quotes its source</h2>
              <p>
                Verbatim, with a link. Nothing is paraphrased into something you can't go and check
                for yourself in ten seconds.
              </p>
            </div>
          </li>
          <li>
            <span className="entry__promise-mark" aria-hidden />
            <div>
              <h2>Nothing is true until you say so</h2>
              <p>
                What the extraction produces is a draft. You confirm, edit, or reject each claim —
                and your name stays attached to the call you made.
              </p>
            </div>
          </li>
        </ul>
      </aside>
    </div>
  );
}
