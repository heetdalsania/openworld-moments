// SPDX-License-Identifier: AGPL-3.0-or-later
// Hash routes, so a UI reload returns to the same screen.
import { useEffect, useState } from "react";

export type Route =
  | { view: "library" }
  | { view: "asset"; id: string }
  | { view: "settings" }
  | { view: "calibration" }
  | { view: "phone" }
  | { view: "sessions" }
  | { view: "session"; id: string };

const ASSET = /^#\/asset\/(ast_[0-9A-HJKMNP-TV-Z]{26})$/;
const SESSION = /^#\/session\/(ses_[0-9A-HJKMNP-TV-Z]{26})$/;

export function parseRoute(hash: string): Route {
  const asset = ASSET.exec(hash);
  if (asset?.[1]) return { view: "asset", id: asset[1] };
  if (hash === "#/calibration") return { view: "calibration" };
  if (hash === "#/settings") return { view: "settings" };
  if (hash === "#/phone") return { view: "phone" };
  if (hash === "#/sessions") return { view: "sessions" };
  const session = SESSION.exec(hash);
  if (session?.[1]) return { view: "session", id: session[1] };
  return { view: "library" };
}

export function routeHref(route: Route): string {
  switch (route.view) {
    case "library":
      return "#/library";
    case "asset":
      return `#/asset/${route.id}`;
    case "calibration":
      return "#/calibration";
    case "settings":
      return "#/settings";
    case "phone":
      return "#/phone";
    case "sessions":
      return "#/sessions";
    case "session":
      return `#/session/${route.id}`;
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
