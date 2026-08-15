/* The front door.
 *
 * The old build had none: it dropped you straight onto whichever feature loaded
 * first, with no sense of where you were or what else existed. This screen
 * answers "what am I working on, and what needs me" before anything else.
 *
 * It doubles as one product's home when `focusProductId` is set — the same list,
 * narrowed — so there is one place features are listed rather than two that can
 * disagree.
 */

import { useCallback, useMemo, useState } from "react";
import { ApiError, api, canWrite } from "../api";
import type { FeatureScope, Product, Role } from "../api";
import { needsRuling, summarize } from "../review";
import { UNASSIGNED, linkProps } from "../router";
import type { Route } from "../router";

export function ProductsPage({
  products,
  scopes,
  role,
  navigate,
  onCreated,
  focusProductId,
}: {
  products: Product[];
  scopes: FeatureScope[];
  role: Role;
  navigate: (route: Route, replace?: boolean) => void;
  onCreated: () => void;
  focusProductId: string | null;
}) {
  const writable = canWrite(role);
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);

  const focused = useMemo(
    () =>
      focusProductId === UNASSIGNED
        ? { id: UNASSIGNED, name: "Not filed yet" }
        : (products.find((product) => product.id === focusProductId) ?? null),
    [focusProductId, products],
  );

  const featuresOf = useCallback(
    (productId: string) =>
      scopes.filter((scope) => (scope.product_id ?? UNASSIGNED) === productId),
    [scopes],
  );

  const create = useCallback(async () => {
    const trimmed = name.trim();
    if (!trimmed) return;
    try {
      await api.createProduct(trimmed);
      setName("");
      setAdding(false);
      setError(null);
      onCreated();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Couldn't create that product.");
    }
  }, [name, onCreated]);

  if (focused) {
    const features = featuresOf(focused.id);
    const unfiled = focused.id === UNASSIGNED;
    return (
      <div className="pad">
        {/* The Sources and Conflicts links that used to sit here are gone: the
            rail now carries both as product-level nav, with a live conflict
            count, so keeping them meant Conflicts appeared twice on one screen
            and the two could disagree. */}
        <div className="page-head">
          <h1>{focused.name}</h1>
        </div>
        <p className="page-sub">{summaryLine(features)}</p>
        {features.length === 0 && !unfiled && (
          <div className="notice">
            {writable ? (
              <>
                Nothing here yet.{" "}
                <a {...linkProps({ name: "sources", productId: focused.id }, navigate)}>
                  Connect a source
                </a>{" "}
                and pull in one pull request or one epic to see what Atlas makes of it.
              </>
            ) : (
              "Nothing here yet. Ask an editor to connect a source."
            )}
          </div>
        )}
        <Worklist features={features} productId={focused.id} navigate={navigate} />
      </div>
    );
  }

  return (
    <div className="pad">
      <div className="page-head">
        <h1>Your products</h1>
        {writable && !adding && (
          <button type="button" className="link-button" onClick={() => setAdding(true)}>
            New product
          </button>
        )}
      </div>
      <p className="page-sub">
        Each product has its own sources — its own GitHub org, its own Jira site — and its own
        features. Nothing crosses between them.
      </p>

      {error && <div className="notice notice--error">{error}</div>}

      {adding && (
        <div className="composer">
          <input
            autoFocus
            value={name}
            placeholder="e.g. Acme Web"
            onChange={(event) => setName(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") void create();
              if (event.key === "Escape") setAdding(false);
            }}
          />
          <div className="composer__row">
            <button
              type="button"
              className="action action--primary"
              onClick={() => void create()}
              disabled={!name.trim()}
            >
              Create
            </button>
            <button type="button" className="action" onClick={() => setAdding(false)}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {products.length === 0 && !adding && (
        <div className="notice">
          No products yet.{" "}
          {writable ? "Create one to give your features a home." : "Ask an editor to create one."}
        </div>
      )}

      <div className="cards">
        {products.map((product) => {
          const features = featuresOf(product.id);
          return (
            <a
              key={product.id}
              className="card-link"
              {...linkProps({ name: "product", productId: product.id }, navigate)}
            >
              <span className="card-link__name">{product.name}</span>
              <span className="card-link__meta">
                <span>
                  {features.length} feature{features.length === 1 ? "" : "s"}
                </span>
                <span>{workSummary(features)}</span>
              </span>
            </a>
          );
        })}
        {featuresOf(UNASSIGNED).length > 0 && (
          <a
            className="card-link"
            {...linkProps({ name: "product", productId: UNASSIGNED }, navigate)}
          >
            <span className="card-link__name">Not filed yet</span>
            <span className="card-link__meta">
              <span>{featuresOf(UNASSIGNED).length} feature(s)</span>
              <span>ingested before products existed</span>
            </span>
          </a>
        )}
      </div>
    </div>
  );
}

/* The product home, as a worklist rather than a directory.
 *
 * It used to be a grid of identical cards: every feature looked the same and
 * none of them said where to start, so the only way to find outstanding work
 * was to open features one at a time and look. Now the screen is ordered by
 * what is owed — disagreements first, then backlog — and everything already
 * settled drops to a quiet list underneath.
 *
 * A conflict outranks a backlog on purpose: an unreviewed claim is work, but a
 * conflict is a decision nobody has made, and it is the one thing no single
 * source tool could have shown you (TRD §5.2).
 */
function Worklist({
  features,
  productId,
  navigate,
}: {
  features: FeatureScope[];
  productId: string;
  navigate: (route: Route, replace?: boolean) => void;
}) {
  const pending = needsRuling(features);
  const settled = features.filter((scope) => !pending.includes(scope));

  if (features.length === 0) return null;

  return (
    <>
      {pending.length > 0 && (
        <section className="work">
          <h2 className="work__head">Needs your ruling</h2>
          <ul className="work__list">
            {pending.map((scope) => (
              <li key={scope.id}>
                <a
                  className="work__row"
                  {...linkProps({ name: "feature", productId, featureId: scope.id }, navigate)}
                >
                  <span className="work__title">{scope.title}</span>
                  <span className="work__state">
                    {scope.counts.conflicts > 0 && (
                      <span className="work__conflicts">
                        ⚑ {scope.counts.conflicts}{" "}
                        {scope.counts.conflicts === 1 ? "conflict" : "conflicts"}
                      </span>
                    )}
                    {scope.counts.unreviewed > 0 && (
                      <span className="work__left">{scope.counts.unreviewed} to review</span>
                    )}
                    <span className="work__meter" aria-hidden>
                      <span
                        style={{
                          width: `${Math.round(((scope.counts.total - scope.counts.unreviewed) / Math.max(scope.counts.total, 1)) * 100)}%`,
                        }}
                      />
                    </span>
                    <span className="work__go">Review →</span>
                  </span>
                </a>
              </li>
            ))}
          </ul>
        </section>
      )}

      {settled.length > 0 && (
        <section className="work work--settled">
          <h2 className="work__head">Settled</h2>
          <ul className="work__list">
            {settled.map((scope) => (
              <li key={scope.id}>
                <a
                  className="work__row"
                  {...linkProps({ name: "feature", productId, featureId: scope.id }, navigate)}
                >
                  <span className="work__title">{scope.title}</span>
                  <span className="work__state">
                    <span className="work__done">✓ all {scope.counts.total} reviewed</span>
                  </span>
                </a>
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}

/** What the product owes you, in one line, instead of "4 features". */
function summaryLine(features: FeatureScope[]): string {
  if (features.length === 0) return "Nothing has been ingested into this product yet.";
  const { unreviewed, conflicts } = summarize(features);
  if (unreviewed === 0 && conflicts === 0) {
    return `${features.length} feature${features.length === 1 ? "" : "s"} — every claim reviewed.`;
  }
  const parts: string[] = [];
  if (conflicts > 0) parts.push(`${conflicts} ${conflicts === 1 ? "conflict" : "conflicts"}`);
  if (unreviewed > 0) parts.push(`${unreviewed} claim${unreviewed === 1 ? "" : "s"} to review`);
  return `${features.length} feature${features.length === 1 ? "" : "s"} · ${parts.join(" · ")}.`;
}

/* On the all-products screen a card said "assembled from gh + jr", which is
   true of nearly every card and so distinguishes none of them. What tells a PM
   which product to open is what it owes them. */
const workSummary = (features: FeatureScope[]): string => {
  if (features.length === 0) return "nothing ingested yet";
  const { unreviewed, conflicts } = summarize(features);
  if (conflicts > 0) return `${conflicts} ${conflicts === 1 ? "conflict" : "conflicts"} · ${unreviewed} to review`;
  return unreviewed > 0 ? `${unreviewed} to review` : "all reviewed";
};
