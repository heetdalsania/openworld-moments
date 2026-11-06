// SPDX-License-Identifier: AGPL-3.0-or-later
// Hash routes, so a UI reload returns to the same screen.
import { useEffect, useState } from "react";

export type Route = { view: "library" } | { view: "asset"; id: string } | { view: "settings" };

const ASSET = /^#\/asset\/(ast_[0-9A-HJKMNP-TV-Z]{26})$/;

export function parseRoute(hash: string): Route {
  const asset = ASSET.exec(hash);
  if (asset?.[1]) return { view: "asset", id: asset[1] };
  if (hash === "#/settings") return { view: "settings" };
  return { view: "library" };
}

export function routeHref(route: Route): string {
  switch (route.view) {
    case "library":
      return "#/library";
    case "asset":
      return `#/asset/${route.id}`;
    case "settings":
      return "#/settings";
  }
}

export function navigate(route: Route): void {
  window.location.hash = routeHref(route);
}

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parseRoute(window.location.hash));
  useEffect(() => {
    const update = () => setRoute(parseRoute(window.location.hash));
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);
  return route;
}
