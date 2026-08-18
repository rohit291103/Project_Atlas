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
import { SOURCE_BADGES, SOURCE_LABELS, needsRuling, summarize } from "../review";
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
        {/* The one-line summary used to sit here unconditionally and then the
            dashboard restated all four of its numbers immediately underneath.
            It survives only for the case where there are no figures to show,
            which is the case it was actually needed for. */}
        {features.length === 0 && <p className="page-sub">{summaryLine(features)}</p>}

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

        {features.length > 0 && (
          <Dashboard features={features} productId={focused.id} navigate={navigate} />
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

/* The product's overview, above the worklist.
 *
 * The rail's "Overview" used to open a title, a one-line summary and a list of
 * features. That is a directory with a sentence on top, and it answered the
 * question a PM asks second ("which feature do I open?") without ever answering
 * the one they ask first: *how much is there, and how much of it is mine to do?*
 * Four counts and a meter answer it in one glance, and the worklist underneath
 * is then the dive-in rather than the whole screen.
 *
 * Every figure comes from `ScopeCounts` on the projection — the same source the
 * rail badges, the Conflicts nav entry and the review bar read — so the
 * dashboard can never disagree with the screens it links to. Nothing here is
 * derived a second way, which is the failure mode a dashboard invites.
 */
function Dashboard({
  features,
  productId,
  navigate,
}: {
  features: FeatureScope[];
  productId: string;
  navigate: (route: Route, replace?: boolean) => void;
}) {
  const work = summarize(features);
  const pending = needsRuling(features);
  const next = pending[0] ?? null;
  const reviewed = work.total - work.unreviewed;
  const percent = work.total ? Math.round((reviewed / work.total) * 100) : 0;
  const backlog = features.filter((scope) => scope.counts.unreviewed > 0).length;
  const contested = features.filter((scope) => scope.counts.conflicts > 0).length;

  /* Which tools this product was actually assembled out of, read off the
     ingestion runs already on each row. "Two sources connected" is a fact about
     configuration; this is a fact about the data, and they are not the same
     thing the day a connection exists but has pulled nothing. */
  const sources = [
    ...new Map(
      features.flatMap((scope) =>
        scope.runs.map(
          (run) => [SOURCE_BADGES[run.source_type], SOURCE_LABELS[run.source_type]] as const,
        ),
      ),
    ),
  ];

  return (
    <section className="dash">
      <div className="stats">
        <div className="stat">
          <span className="stat__label">Features</span>
          <b className="stat__n">{features.length}</b>
          <span className="stat__note">
            {sources.length > 0 ? (
              <>
                assembled from{" "}
                {sources.map(([badge, label]) => (
                  <span className="badge" key={badge} title={label}>
                    {badge}
                  </span>
                ))}
              </>
            ) : (
              "nothing ingested yet"
            )}
          </span>
        </div>

        <div className="stat">
          <span className="stat__label">Claims extracted</span>
          <b className="stat__n">{work.total}</b>
          <span className="stat__note">
            {work.total === 0 ? "nothing extracted yet" : `${percent}% ruled on`}
          </span>
        </div>

        {/* A draft is not a fact until a person acts on it (Engineering
            Philosophy §2), so "needs review" is the product's real backlog and
            not a nag — it is stated in neutral ink for exactly that reason. */}
        <div className={`stat${work.unreviewed > 0 ? " stat--open" : " stat--clear"}`}>
          <span className="stat__label">Needs review</span>
          <b className="stat__n">{work.unreviewed}</b>
          <span className="stat__note">
            {work.unreviewed === 0
              ? "every claim ruled on"
              : `across ${backlog} ${backlog === 1 ? "feature" : "features"}`}
          </span>
        </div>

        {/* The one loud tile, and only when it has something to be loud about. A
            conflict outranks a backlog: an unreviewed claim is work somebody has
            yet to do, a conflict is a decision nobody has made (TRD §5.2). */}
        <div className={`stat${work.conflicts > 0 ? " stat--conflict" : " stat--clear"}`}>
          <span className="stat__label">Unresolved conflicts</span>
          <b className="stat__n">{work.conflicts}</b>
          <span className="stat__note">
            {work.conflicts === 0 ? (
              "no disagreements"
            ) : (
              <a className="stat__go" {...linkProps({ name: "conflicts", productId }, navigate)}>
                in {contested} {contested === 1 ? "feature" : "features"} — rule on them →
              </a>
            )}
          </span>
        </div>
      </div>

      {work.total > 0 && (
        <div className="dash__meter">
          <div className="dash__meter-line">
            <span>
              <b>{reviewed}</b> of {work.total} claims reviewed
            </span>
            {next && (
              <a
                className="action action--primary"
                {...linkProps({ name: "feature", productId, featureId: next.id }, navigate)}
              >
                Review next →
              </a>
            )}
          </div>
          <span className="meter__track meter__track--lg">
            <span className="meter__fill" style={{ width: `${percent}%` }} />
          </span>
        </div>
      )}
    </section>
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
