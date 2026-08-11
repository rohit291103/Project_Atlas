/* The entry surface. Phase 1 auth is a shared passphrase plus the reviewer's
 * name — the name becomes the `actor` on every event they write, so the audit
 * record names a real person rather than a placeholder
 * (docs/decisions/2026-08-11-api-frontend-module-boundary.md §4).
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
        <div>
          <h1 className="signin__title">Atlas</h1>
          <p className="signin__sub">Review what was extracted, and decide what is true.</p>
        </div>

        <div className="field">
          <label htmlFor="name">Your name</label>
          <input
            id="name"
            value={name}
            autoComplete="name"
            onChange={(event) => setName(event.target.value)}
          />
          <span className="field__note">Recorded on every decision you make.</span>
        </div>

        <div className="field">
          <label htmlFor="passphrase">Passphrase</label>
          <input
            id="passphrase"
            type="password"
            value={passphrase}
            autoComplete="current-password"
            onChange={(event) => setPassphrase(event.target.value)}
          />
        </div>

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
