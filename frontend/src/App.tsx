/* Shell: session gate, left rail of feature scopes, and the review page.
 *
 * Phase 1 has one workspace and no routing library — the rail selects a scope
 * and the page renders it. Server state is `fetch` + local state; no state
 * library until optimistic updates actually demand cache invalidation
 * (docs/decisions/2026-08-11-api-frontend-module-boundary.md §6).
 */

import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "./api";
import type { FeatureScope, Role } from "./api";
import { ReviewPage } from "./components/ReviewPage";
import { SignIn } from "./components/SignIn";

export function App() {
  const [actor, setActor] = useState<string | null>(null);
  const [role, setRole] = useState<Role>("viewer");
  const [checking, setChecking] = useState(true);
  const [signInError, setSignInError] = useState<string | null>(null);
  const [scopes, setScopes] = useState<FeatureScope[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [railError, setRailError] = useState<string | null>(null);

  // A returning reviewer still holds a valid cookie; don't make them sign in again.
  useEffect(() => {
    api
      .currentSession()
      .then((session) => {
        setActor(session.actor);
        setRole(session.role);
      })
      .catch(() => setActor(null))
      .finally(() => setChecking(false));
  }, []);

  useEffect(() => {
    if (!actor) return;
    api
      .featureScopes()
      .then((loaded) => {
        setScopes(loaded);
        setSelected((current) => current ?? loaded[0]?.id ?? null);
        setRailError(null);
      })
      .catch((caught: unknown) =>
        setRailError(caught instanceof ApiError ? caught.message : "Couldn't load features."),
      );
  }, [actor]);

  const signIn = useCallback(async (passphrase: string, name: string) => {
    try {
      const session = await api.signIn(passphrase, name);
      setActor(session.actor);
      setRole(session.role);
      setSignInError(null);
    } catch (caught) {
      setSignInError(
        caught instanceof ApiError ? caught.message : "Couldn't sign in — is the API running?",
      );
    }
  }, []);

  const signOut = useCallback(async () => {
    await api.signOut().catch(() => undefined);
    setActor(null);
    setScopes([]);
    setSelected(null);
  }, []);

  if (checking) return <div className="signin" />;
  if (!actor) {
    return <SignIn onSignIn={(passphrase, name) => void signIn(passphrase, name)} error={signInError} />;
  }

  return (
    <div className="shell">
      <nav className="rail">
        <div className="rail__brand">Atlas</div>
        <div>
          <div className="rail__label">Features</div>
          {railError && <div className="notice notice--error">{railError}</div>}
          {!railError && scopes.length === 0 && (
            <div className="rail__foot">
              Nothing ingested yet. Run <code>atlas ingest</code> from the CLI.
            </div>
          )}
          <ul className="rail__list">
            {scopes.map((scope) => (
              <li key={scope.id}>
                <button
                  type="button"
                  className={`rail__item ${scope.id === selected ? "rail__item--active" : ""}`}
                  onClick={() => setSelected(scope.id)}
                  title={scope.title}
                >
                  <span className="rail__item-title">{scope.title}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
        <div className="rail__foot">
          <span>
            Signed in as {actor} · {role}
          </span>
          <button type="button" className="link-button" onClick={() => void signOut()}>
            Sign out
          </button>
        </div>
      </nav>

      {selected ? (
        <ReviewPage key={selected} scopeId={selected} actor={actor} role={role} />
      ) : (
        <main className="main">
          <div className="notice">Select a feature to start reviewing.</div>
        </main>
      )}
    </div>
  );
}
