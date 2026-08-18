/* Shell: the public/private split, the session gate, the rail, and the routed screen.
 *
 * Three things changed from the first cut, each fixing something specific. The
 * selected feature used to be component state — no URL, no back button, refresh
 * landing you on whichever feature loaded first. It is now a real route
 * (`router.ts`). Features are grouped under the *product* they belong to,
 * because a PM works on several at once and each has its own GitHub org and its
 * own Jira site (docs/architecture/product-model-and-frontend-rebuild-v1.md §2).
 * And as of slice 2B there is a **public half** — a landing page and a sign-in
 * route — so the app has a front door rather than a login form with nothing
 * behind it to explain itself.
 *
 * The gate is one rule, stated once: a private route with no session sends you
 * to `/signin`, and a public route with a session sends you on to `/app`. Both
 * use `replace`, so the browser's back button never walks you back into a
 * redirect loop.
 *
 * Server state is still `fetch` + local state; no state library until optimistic
 * updates actually demand cache invalidation
 * (docs/decisions/2026-08-11-api-frontend-module-boundary.md §6).
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api } from "./api";
import type { FeatureScope, Product, Role } from "./api";
import { IconConflict, IconOverview, IconSources } from "./components/icons";
import { Loading } from "./components/Loading";
import { ProductSwitcher } from "./components/ProductSwitcher";
import { landingProductId, rememberProduct } from "./lastProduct";
import { ConflictsPage } from "./pages/ConflictsPage";
import { LandingPage } from "./pages/LandingPage";
import { ProductsPage } from "./pages/ProductsPage";
import { ReviewPage } from "./pages/ReviewPage";
import { SignInPage } from "./pages/SignInPage";
import { SourcesPage } from "./pages/SourcesPage";
import { summarize } from "./review";
import { PUBLIC_ROUTES, UNASSIGNED, linkProps, useRoute } from "./router";
import type { Route } from "./router";
import { THEME_LABELS, useTheme } from "./theme";

/** Features that predate the product layer still need a home in the rail. They
 * get a real, linkable one rather than being hidden — "not filed yet" is a state
 * to act on, not a reason to vanish. */
const UNFILED: Product = { id: UNASSIGNED, name: "Not filed yet" };

export function App() {
  const [route, navigate] = useRoute();
  const [theme, cycleTheme] = useTheme();

  const [actor, setActor] = useState<string | null>(null);
  const [role, setRole] = useState<Role>("viewer");
  const [checking, setChecking] = useState(true);
  const [signInError, setSignInError] = useState<string | null>(null);

  const [products, setProducts] = useState<Product[]>([]);
  const [scopes, setScopes] = useState<FeatureScope[]>([]);
  const [railError, setRailError] = useState<string | null>(null);

  /* A filter over the active product's features — deliberately not a command
     palette. The design baseline defers ⌘K-as-command-surface to v1.x
     (design-system-baseline-v1 §6.9, §8); this is the much smaller thing the
     rail actually needed once a product holds more features than fit on screen.
     ⌘K focuses it because that is the chord every reviewer's hands already
     reach for, and a shortcut that lands somewhere sensible beats one that
     opens a surface we haven't built. */
  const [query, setQuery] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);

  const isPublic = PUBLIC_ROUTES.has(route.name);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        searchRef.current?.focus();
        searchRef.current?.select();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  /* Set only by a fresh sign-in. Without it, *every* visit to /app would bounce
     into a product and "All products" would be a screen you could never reach —
     the trap that turns a helpful default into a cage. */
  const wantsLanding = useRef(false);

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

  // The gate. Runs only once the session check has settled, so a returning user
  // is never bounced to /signin during the moment we don't yet know who they are.
  useEffect(() => {
    if (checking) return;
    if (!actor && !isPublic) navigate({ name: "signin" }, true);
    if (actor && route.name === "signin") navigate({ name: "products" }, true);
  }, [actor, checking, isPublic, navigate, route.name]);

  /* Remember the context on the way *out* of it, so the next sign-in reopens
     the job this person was actually doing. Keyed on the route rather than on
     the switcher, so arriving by deep link or back button counts too. */
  useEffect(() => {
    if (route.name === "products" || route.name === "home" || route.name === "signin") return;
    rememberProduct((route as { productId: string }).productId);
  }, [route]);

  const loadRail = useCallback(async () => {
    try {
      const [loadedProducts, loadedScopes] = await Promise.all([
        api.products(),
        api.featureScopes(),
      ]);
      setProducts(loadedProducts);
      setScopes(loadedScopes);
      setRailError(null);
    } catch (caught) {
      setRailError(caught instanceof ApiError ? caught.message : "Couldn't load your products.");
    }
  }, []);

  useEffect(() => {
    if (actor) void loadRail();
  }, [actor, loadRail]);

  /* Forward a just-signed-in reviewer into the product they left off in. Runs
     after the rail resolves because it needs the real product list to check the
     remembered id against — a product that has since been deleted must fall
     back to the chooser, not to a screen pointed at nothing. */
  useEffect(() => {
    if (!wantsLanding.current || route.name !== "products" || products.length === 0) return;
    wantsLanding.current = false;
    const landing = landingProductId(products);
    if (landing) navigate({ name: "product", productId: landing }, true);
  }, [products, route.name, navigate]);

  const signIn = useCallback(
    async (passphrase: string, name: string) => {
      try {
        const session = await api.signIn(passphrase, name);
        setActor(session.actor);
        setRole(session.role);
        setSignInError(null);
        // Land on the product list only as a fallback. The moment the rail
        // resolves, the effect below forwards to whichever product this person
        // was last inside — the products themselves aren't loaded yet here.
        wantsLanding.current = true;
        navigate({ name: "products" }, true);
      } catch (caught) {
        setSignInError(
          caught instanceof ApiError ? caught.message : "Couldn't sign in. Is the API running?",
        );
      }
    },
    [navigate],
  );

  const signOut = useCallback(async () => {
    await api.signOut().catch(() => undefined);
    setActor(null);
    setProducts([]);
    setScopes([]);
    navigate({ name: "home" });
  }, [navigate]);

  /** Every product that can be switched into, with the unfiled bucket appended
   * only when it has something in it — an empty "Not filed yet" entry is noise. */
  const shelves = useMemo(() => {
    const byProduct = new Map<string, FeatureScope[]>();
    for (const scope of scopes) {
      const key = scope.product_id ?? UNASSIGNED;
      byProduct.set(key, [...(byProduct.get(key) ?? []), scope]);
    }
    const known = products.map((product) => ({
      product,
      features: byProduct.get(product.id) ?? [],
    }));
    const unfiled = byProduct.get(UNASSIGNED) ?? [];
    return unfiled.length ? [...known, { product: UNFILED, features: unfiled }] : known;
  }, [products, scopes]);

  if (checking) return <Loading />;

  if (route.name === "home") {
    return <LandingPage navigate={navigate} signedInAs={actor} />;
  }
  if (route.name === "signin" || !actor) {
    return (
      <SignInPage
        onSignIn={(passphrase, name) => void signIn(passphrase, name)}
        error={signInError}
        navigate={navigate}
      />
    );
  }

  const activeProductId =
    route.name === "products" ? null : (route as { productId: string }).productId;

  // The rail below shows exactly one product's features. Anything cross-product
  // is a deliberate trip to "All products", never the default view.
  const activeShelf = shelves.find((shelf) => shelf.product.id === activeProductId) ?? null;

  const needle = query.trim().toLowerCase();
  const features = activeShelf?.features ?? [];
  const visibleFeatures = needle
    ? features.filter((scope) => scope.title.toLowerCase().includes(needle))
    : features;
  const work = summarize(features);
  // The unfiled bucket is not a real product: no sources to connect, no
  // conflicts screen, and no work meter that means anything.
  const isRealProduct = activeShelf !== null && activeShelf.product.id !== UNASSIGNED;

  return (
    <div className="shell">
      <nav className="rail">
        <a className="rail__brand" {...linkProps({ name: "products" }, navigate)}>
          <span className="rail__glyph" aria-hidden />
          Atlas
        </a>

        {shelves.length > 0 && (
          <ProductSwitcher
            products={shelves.map(({ product, features }) => ({
              id: product.id,
              name: product.name,
              note: `${features.length} ${features.length === 1 ? "feature" : "features"}`,
            }))}
            activeId={activeProductId}
            onPick={(productId) => navigate({ name: "product", productId })}
            onAllProducts={() => navigate({ name: "products" })}
          />
        )}

        {/* The product's own screens, as one flat block of destinations.
            Each of these used to sit under its own mono all-caps group heading —
            "CONNECT" over `Sources`, "REVIEW" over `Conflicts` — which read as a
            single column of alternating type sizes rather than as headings over
            children, because every group held exactly one child. A heading over
            one item is noise a reader has to decode before dismissing.

            The grouping vocabulary survives in the *order* (connect, then
            review) and in the glyphs; a row with an icon is unmistakably a
            place you can go, which is the distinction the labels were failing
            to draw. The one heading left in the rail sits over the feature
            list, which is the only place here a heading has a list to head. */}
        {activeShelf && (
          <div className="rail__nav">
            <a
              className={`rail__nav-item${route.name === "product" ? " is-active" : ""}`}
              aria-current={route.name === "product" ? "page" : undefined}
              {...linkProps({ name: "product", productId: activeShelf.product.id }, navigate)}
            >
              <IconOverview className="rail__nav-icon" />
              <span className="rail__nav-text">Overview</span>
            </a>

            {isRealProduct && (
              <a
                className={`rail__nav-item${route.name === "sources" ? " is-active" : ""}`}
                aria-current={route.name === "sources" ? "page" : undefined}
                {...linkProps({ name: "sources", productId: activeShelf.product.id }, navigate)}
              >
                <IconSources className="rail__nav-icon" />
                <span className="rail__nav-text">Sources</span>
              </a>
            )}

            {isRealProduct && (
              <a
                className={`rail__nav-item${route.name === "conflicts" ? " is-active" : ""}`}
                aria-current={route.name === "conflicts" ? "page" : undefined}
                {...linkProps({ name: "conflicts", productId: activeShelf.product.id }, navigate)}
              >
                <IconConflict className="rail__nav-icon" />
                <span className="rail__nav-text">Conflicts</span>
                {/* Counted as disagreements, not as claims-in-a-disagreement,
                    so this agrees with the screen it opens. */}
                {work.conflicts > 0 && (
                  <span className="rail__badge rail__badge--conflict">{work.conflicts}</span>
                )}
              </a>
            )}
          </div>
        )}

        {/* The feature list's own header, pinned above the scroll along with its
            filter. Both used to be inside the scrolling area, so a product with
            forty features scrolled its own navigation out of reach. */}
        {activeShelf && (
          <div className="rail__section">
            <span className="rail__group-label">Features</span>
            <span className="rail__section-n">{features.length}</span>
          </div>
        )}

        {/* A filter, not a command palette — see the note on `query` above. It
            only appears once there is a feature list for it to act on. */}
        {activeShelf && features.length > 0 && (
          <div className="rail__search">
            <span className="rail__search-icon" aria-hidden>
              ⌕
            </span>
            <input
              ref={searchRef}
              type="search"
              value={query}
              placeholder="Filter features"
              aria-label="Filter features"
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Escape") setQuery("");
              }}
            />
            <kbd aria-hidden>⌘K</kbd>
          </div>
        )}

        <div className="rail__scroll">
          {railError && <div className="notice notice--error">{railError}</div>}
          {!railError && shelves.length === 0 && (
            <p className="rail__hint">No products yet. Create one to give your features a home.</p>
          )}

          {/* On "All products" the rail deliberately holds no feature list —
              there is no active context to list, and showing every product's
              features at once is the interleaving this whole step removes. */}
          {!railError && shelves.length > 0 && !activeShelf && (
            <p className="rail__hint">Pick a product above to see its features.</p>
          )}

          {activeShelf && (
            <ul className="rail__list">
              {features.length === 0 && (
                <li className="rail__hint" role="presentation">
                  Nothing ingested yet.
                </li>
              )}
              {features.length > 0 && visibleFeatures.length === 0 && (
                <li className="rail__hint" role="presentation">
                  No feature matches “{query.trim()}”.
                </li>
              )}
              {visibleFeatures.map((scope) => {
                const target: Route = {
                  name: "feature",
                  productId: activeShelf.product.id,
                  featureId: scope.id,
                };
                const active = route.name === "feature" && route.featureId === scope.id;
                const done = scope.counts.total - scope.counts.unreviewed;
                return (
                  <li key={scope.id}>
                    <a
                      className={`rail__item ${active ? "rail__item--active" : ""}`}
                      aria-current={active ? "page" : undefined}
                      title={scope.title}
                      {...linkProps(target, navigate)}
                    >
                      <span className="rail__item-title">{scope.title}</span>
                      {/* This slot used to hold source badges (`gh·jr`). The
                          datum a PM actually navigates on is how much is left,
                          not which tool fed it — the sources are named on the
                          feature itself and on its cards. Swapping them also
                          gives the title back ~30px before it truncates. */}
                      <span className="rail__count">
                        {/* The flag is what separates the two numbers. Side by
                            side as bare digits, "6 6" reads as one quantity
                            split in half rather than conflicts and backlog. */}
                        {scope.counts.conflicts > 0 && (
                          <span
                            className="rail__badge rail__badge--conflict"
                            title={`${scope.counts.conflicts} unresolved conflict${scope.counts.conflicts === 1 ? "" : "s"}`}
                          >
                            ⚑{scope.counts.conflicts}
                          </span>
                        )}
                        {scope.counts.unreviewed > 0 ? (
                          <span
                            className="rail__badge"
                            title={`${scope.counts.unreviewed} claim${scope.counts.unreviewed === 1 ? "" : "s"} still to review`}
                          >
                            {scope.counts.unreviewed}
                          </span>
                        ) : (
                          <span className="rail__done" title="Every claim reviewed">
                            ✓
                          </span>
                        )}
                      </span>
                      {/* A hairline of progress under the row. The badge says
                          how much is left; this says how far in you already
                          are, which is the difference between "20 to go" on an
                          untouched feature and on one you are nearly through. */}
                      {scope.counts.total > 0 && (
                        <span className="rail__item-meter" aria-hidden>
                          <span style={{ width: `${(done / scope.counts.total) * 100}%` }} />
                        </span>
                      )}
                    </a>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        {/* What is owed, where a SaaS dashboard puts its usage meter. Same
            placement, but the number a PM opens this app to find: how much of
            this product still needs a person. Every figure comes from
            `ScopeCounts` on the projection — the same source the badges and the
            Conflicts screen read, so the rail can never disagree with the screen
            it opens. */}
        {isRealProduct && work.total > 0 && (
          <div className="rail__work">
            <span className="rail__work-label">Work left</span>
            <div className="rail__work-row">
              <span>Reviewed</span>
              <b>
                {work.total - work.unreviewed} / {work.total}
              </b>
            </div>
            <div className="rail__work-meter">
              <span
                style={{
                  width: `${Math.round(((work.total - work.unreviewed) / work.total) * 100)}%`,
                }}
              />
            </div>
            <div className="rail__work-row">
              <span>Conflicts</span>
              {work.conflicts > 0 ? (
                <b className="is-conflict">{work.conflicts} unresolved</b>
              ) : (
                <b className="is-clear">none</b>
              )}
            </div>
          </div>
        )}

        <div className="rail__foot">
          <div className="rail__user">
            <span className="rail__avatar" aria-hidden>
              {actor.trim().charAt(0).toUpperCase() || "?"}
            </span>
            <span className="rail__user-who">
              <b title={actor}>{actor}</b>
              <small>{role}</small>
            </span>
            <button
              type="button"
              className="rail__icon-button"
              onClick={cycleTheme}
              title={THEME_LABELS[theme]}
              aria-label={THEME_LABELS[theme]}
            >
              {theme === "dark" ? "☾" : theme === "light" ? "☀" : "◐"}
            </button>
          </div>
          <div className="rail__foot-row">
            <a className="link-button" {...linkProps({ name: "products" }, navigate)}>
              All products
            </a>
            <button type="button" className="link-button" onClick={() => void signOut()}>
              Sign out
            </button>
          </div>
        </div>
      </nav>

      <main className="main">
        <Screen
          route={route}
          navigate={navigate}
          actor={actor}
          role={role}
          products={products}
          scopes={scopes}
          activeProductId={activeProductId}
          onChanged={() => void loadRail()}
        />
      </main>
    </div>
  );
}

function Screen({
  route,
  navigate,
  actor,
  role,
  products,
  scopes,
  activeProductId,
  onChanged,
}: {
  route: Route;
  navigate: (route: Route, replace?: boolean) => void;
  actor: string;
  role: Role;
  products: Product[];
  scopes: FeatureScope[];
  activeProductId: string | null;
  onChanged: () => void;
}) {
  if (route.name === "feature") {
    return (
      <ReviewPage
        key={route.featureId}
        scopeId={route.featureId}
        productId={route.productId}
        actor={actor}
        role={role}
        navigate={navigate}
      />
    );
  }
  if (route.name === "sources") {
    const product = products.find((candidate) => candidate.id === route.productId);
    return (
      <SourcesPage
        key={route.productId}
        productId={route.productId}
        productName={product?.name ?? "this product"}
        scopes={scopes.filter((scope) => scope.product_id === route.productId)}
        role={role}
        navigate={navigate}
        onIngested={onChanged}
      />
    );
  }
  if (route.name === "conflicts") {
    return (
      <ConflictsPage
        productId={route.productId}
        scopes={scopes}
        role={role}
        navigate={navigate}
      />
    );
  }
  return (
    <ProductsPage
      products={products}
      scopes={scopes}
      role={role}
      navigate={navigate}
      onCreated={onChanged}
      focusProductId={route.name === "product" ? activeProductId : null}
    />
  );
}
