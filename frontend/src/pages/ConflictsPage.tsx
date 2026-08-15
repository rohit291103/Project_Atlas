/* Conflicts as objects, not annotations.
 *
 * `conflicts_with` is the one thing no single tool could have told you: a
 * requirement in a PR contradicting a decision in Jira. The old build rendered
 * it as an amber line inside a card — drawn on *both* endpoints, so five
 * conflicts became ten banners scattered down a long page, and the two claims
 * were never on screen together. You cannot rule on a disagreement you can only
 * read half of.
 *
 * Here each pair is one object with both sides and both excerpts, and either
 * side can be ruled on in place. Confirming one side does not resolve the
 * conflict (TRD §5.2) and the pair keeps saying so.
 */

import { useCallback, useEffect, useState } from "react";
import { ApiError, api, canWrite } from "../api";
import type { FeatureScope, Node, Role } from "../api";
import { SOURCE_BADGES, TYPE_TAGS, conflictPairs, pipsFor, sourceLabel } from "../review";
import type { ConflictPair } from "../review";
import { UNASSIGNED, linkProps } from "../router";
import type { Route } from "../router";

type Entry = ConflictPair & { scope: FeatureScope };

export function ConflictsPage({
  productId,
  scopes,
  role,
  navigate,
}: {
  productId: string;
  scopes: FeatureScope[];
  role: Role;
  navigate: (route: Route, replace?: boolean) => void;
}) {
  const writable = canWrite(role);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const mine = scopes.filter((scope) => (scope.product_id ?? UNASSIGNED) === productId);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      // One request per feature. There is deliberately no cross-feature conflicts
      // endpoint: which conflicts matter and how they are grouped is a
      // presentation decision, and the API does not make those.
      const loaded = await Promise.all(
        mine.map(async (scope) => ({ scope, detail: await api.featureScope(scope.id) })),
      );
      setEntries(
        loaded.flatMap(({ scope, detail }) =>
          conflictPairs(detail).map((pair) => ({ ...pair, scope })),
        ),
      );
      setError(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Couldn't load conflicts.");
    } finally {
      setLoading(false);
    }
    // `mine` is derived from `scopes` on each render; keying the effect on the
    // ids keeps it from re-running on every parent render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scopes.map((scope) => scope.id).join(","), productId]);

  useEffect(() => {
    void load();
  }, [load]);

  const rule = useCallback(
    async (call: () => Promise<Node>) => {
      try {
        const updated = await call();
        setEntries((current) =>
          current.map((entry) => ({
            ...entry,
            a: entry.a.id === updated.id ? updated : entry.a,
            b: entry.b.id === updated.id ? updated : entry.b,
          })),
        );
      } catch (caught) {
        setError(caught instanceof ApiError ? caught.message : "That didn't save.");
      }
    },
    [],
  );

  if (loading) {
    return (
      <div className="pad">
        <div className="skeleton" />
        <div className="skeleton" />
      </div>
    );
  }

  const crossSource = entries.filter((entry) => entry.crossSource).length;

  return (
    <div className="pad">
      <div className="page-head">
        <h1>
          {entries.length} conflict{entries.length === 1 ? "" : "s"}
        </h1>
        <a className="link-button" {...linkProps({ name: "product", productId }, navigate)}>
          Back to features
        </a>
      </div>
      <p className="page-sub">
        {entries.length === 0
          ? "Nothing in this product contradicts anything else — on the evidence gathered so far."
          : `${crossSource} of them cross sources, which is the kind no single tool could have shown you. Ruling on one side does not resolve a conflict; both claims stay on the record.`}
      </p>

      {error && <div className="notice notice--error">{error}</div>}

      {entries.map((entry) => (
        <article className="pair" key={entry.id}>
          <div className="pair__head">
            <span className="pair__mark" aria-hidden>
              ⚠
            </span>
            <span>
              {entry.crossSource ? (
                <>
                  <b>{sourceLabel(entry.a)}</b> disagrees with <b>{sourceLabel(entry.b)}</b>
                </>
              ) : (
                <>Two claims from {sourceLabel(entry.a)} disagree</>
              )}
            </span>
            <a
              className="link-button"
              {...linkProps(
                { name: "feature", productId, featureId: entry.scope.id },
                navigate,
              )}
            >
              {entry.scope.title}
            </a>
          </div>
          <div className="pair__grid">
            <Side node={entry.a} writable={writable} onRule={rule} />
            <div className="vs" aria-hidden>
              VS
            </div>
            <Side node={entry.b} writable={writable} onRule={rule} />
          </div>
        </article>
      ))}
    </div>
  );
}

function Side({
  node,
  writable,
  onRule,
}: {
  node: Node;
  writable: boolean;
  onRule: (call: () => Promise<Node>) => Promise<void>;
}) {
  const ref = node.source_refs[0];
  return (
    <div className="side">
      <div className="side__top">
        <span className="tag">{TYPE_TAGS[node.type as keyof typeof TYPE_TAGS]}</span>
        <span className="pips">{pipsFor(node)}</span>
        <span className={`status status--${node.status}`}>{node.status}</span>
      </div>
      <p className="side__claim">{node.content}</p>
      {ref && (
        <p className="side__ex">
          {SOURCE_BADGES[ref.source_type]} {ref.external_id} · “{ref.excerpt}”
        </p>
      )}
      {writable && (
        <div className="side__acts">
          <button
            type="button"
            className="action action--sm action--primary"
            onClick={() => void onRule(() => api.confirm(node.id))}
          >
            ✓ Confirm this side
          </button>
          <button
            type="button"
            className="action action--sm"
            onClick={() => void onRule(() => api.reject(node.id))}
          >
            ✕ Reject
          </button>
        </div>
      )}
    </div>
  );
}
