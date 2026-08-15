/* Real URLs, which is the fix for "I can't navigate this".
 *
 * Before this, the selected feature was component state: no route, no back
 * button, refresh dropped you on whichever feature loaded first, and no view
 * could be linked to anyone. Every screen now has an address.
 *
 * Hand-rolled rather than `react-router` on purpose — there are four routes and
 * no nesting, guards or loaders, so the library would be more surface than the
 * problem. The public shape here (`parse`, `href`, `useRoute`) is deliberately
 * the subset react-router would give us, so swapping it in later is a mechanical
 * change if the route table ever grows teeth.
 */

import { useCallback, useEffect, useState } from "react";

/** A feature ingested before products existed has no product to sit under. It
 * gets a real, linkable address rather than being hidden — "not filed yet" is a
 * state a PM has to be able to see and act on, not a reason to disappear. */
export const UNASSIGNED = "unassigned";

export type Route =
  | { name: "home" }
  | { name: "signin" }
  | { name: "products" }
  | { name: "product"; productId: string }
  | { name: "sources"; productId: string }
  | { name: "conflicts"; productId: string }
  | { name: "feature"; productId: string; featureId: string };

export function parse(pathname: string): Route {
  const parts = pathname.split("/").filter(Boolean);
  if (parts.length === 0) return { name: "home" };
  if (parts[0] === "signin") return { name: "signin" };
  if (parts[0] === "app") return { name: "products" };
  if (parts[0] !== "p" || !parts[1]) return { name: "home" };
  const productId = parts[1];
  if (parts[2] === "sources") return { name: "sources", productId };
  if (parts[2] === "conflicts") return { name: "conflicts", productId };
  if (parts[2] === "f" && parts[3]) return { name: "feature", productId, featureId: parts[3] };
  return { name: "product", productId };
}

export function href(route: Route): string {
  switch (route.name) {
    case "home":
      return "/";
    case "signin":
      return "/signin";
    case "products":
      return "/app";
    case "product":
      return `/p/${route.productId}`;
    case "sources":
      return `/p/${route.productId}/sources`;
    case "conflicts":
      return `/p/${route.productId}/conflicts`;
    case "feature":
      return `/p/${route.productId}/f/${route.featureId}`;
  }
}

/** Routes anyone may see without a session.
 *
 * `/` is now the marketing page rather than the product list, which is the one
 * behavioural change to an existing address: a signed-in visitor is forwarded
 * from it to `/app`, so nobody who has already signed in lands on a pitch. */
export const PUBLIC_ROUTES: ReadonlySet<Route["name"]> = new Set(["home", "signin"]);

/** The current route, plus a navigate that pushes real history.
 *
 * `popstate` is what makes the browser's own back button work — the thing whose
 * absence made the old build feel like a dead end.
 */
export function useRoute(): [Route, (route: Route, replace?: boolean) => void] {
  const [route, setRoute] = useState<Route>(() => parse(window.location.pathname));

  useEffect(() => {
    const onPop = () => setRoute(parse(window.location.pathname));
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const navigate = useCallback((next: Route, replace = false) => {
    const url = href(next);
    if (replace) window.history.replaceState(null, "", url);
    else window.history.pushState(null, "", url);
    setRoute(next);
  }, []);

  return [route, navigate];
}

/** Anchor props for a route: a real `href` so middle-click, ⌘-click and "copy
 * link address" all behave, with the plain-click case intercepted for the SPA. */
export function linkProps(
  route: Route,
  navigate: (route: Route, replace?: boolean) => void,
): { href: string; onClick: (event: React.MouseEvent) => void } {
  return {
    href: href(route),
    onClick: (event: React.MouseEvent) => {
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
      event.preventDefault();
      navigate(route);
    },
  };
}
