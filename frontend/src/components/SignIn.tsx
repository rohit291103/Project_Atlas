/* The entry surface. Phase 1 auth is a shared passphrase plus the reviewer's
 * name — the name becomes the `actor` on every event they write, so the audit
 * record names a real person rather than a placeholder
 * (docs/decisions/2026-08-11-api-frontend-module-boundary.md §4).
 *
 * The name field says what it is *for* rather than just what it is. Someone
 * typing "p" or "test" here has quietly broken the audit trail, and the only
 * moment to prevent that is before they submit.
 */

import { useState } from "react";

export function SignIn({
  onSignIn,
  error,
}: {
  onSignIn: (passphrase: string, name: string) => void;
  error: string | null;
}) {
  const [passphrase, setPassphrase] = useState("");
  const [name, setName] = useState("");

  return (
    <div className="signin">
      <form
        className="signin__card"
        onSubmit={(event) => {
          event.preventDefault();
          onSignIn(passphrase, name.trim());
        }}
      >
        <div className="signin__mark">
          <span className="rail__glyph" aria-hidden />
          Atlas
        </div>
        <p className="signin__lede">
          Everything your team already wrote about a feature, gathered in one place — so you can
          decide what is actually true.
        </p>

        <label htmlFor="name">
          Your name
          <input
            id="name"
            value={name}
            autoComplete="name"
            placeholder="Priya Raman"
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <p className="signin__note">
          Recorded on every decision you make, so anyone reading the feature later can see who
          confirmed what.
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
      </form>
    </div>
  );
}
