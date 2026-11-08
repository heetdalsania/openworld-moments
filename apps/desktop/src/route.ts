// SPDX-License-Identifier: AGPL-3.0-or-later
// Hash routes, so a UI reload returns to the same screen.
import { useEffect, useState } from "react";

export type Route =
  | { view: "library" }
  | { view: "projects" }
  | { view: "project"; id: string }
  | { view: "asset"; id: string; at?: number }
  | { view: "settings" }
  | { view: "calibration" }
  | { view: "phone" }
  | { view: "sessions" }
  | { view: "session"; id: string; at?: number }
  | { view: "search" };

const PROJECT = /^#\/project\/(prj_[0-9A-HJKMNP-TV-Z]{26})$/;
// An optional "@<ms>" opens the item at that time (M26 search results).
const ASSET = /^#\/asset\/(ast_[0-9A-HJKMNP-TV-Z]{26})(?:@([0-9]{1,9}))?$/;
const SESSION = /^#\/session\/(ses_[0-9A-HJKMNP-TV-Z]{26})(?:@([0-9]{1,9}))?$/;

function at(match: RegExpExecArray): { at?: number } {
  return match[2] !== undefined ? { at: Number(match[2]) } : {};
}

export function parseRoute(hash: string): Route {
  const project = PROJECT.exec(hash);
  if (project?.[1]) return { view: "project", id: project[1] };
  if (hash === "#/projects") return { view: "projects" };
  const asset = ASSET.exec(hash);
  if (asset?.[1]) return { view: "asset", id: asset[1], ...at(asset) };
  if (hash === "#/calibration") return { view: "calibration" };
  if (hash === "#/settings") return { view: "settings" };
  if (hash === "#/phone") return { view: "phone" };
  if (hash === "#/sessions") return { view: "sessions" };
  const session = SESSION.exec(hash);
  if (session?.[1]) return { view: "session", id: session[1], ...at(session) };
  if (hash === "#/search") return { view: "search" };
  return { view: "library" };
}

export function routeHref(route: Route): string {
  switch (route.view) {
    case "projects":
      return "#/projects";
    case "project":
      return `#/project/${route.id}`;
    case "library":
      return "#/library";
    case "asset":
      return `#/asset/${route.id}${route.at !== undefined ? `@${route.at}` : ""}`;
    case "calibration":
      return "#/calibration";
    case "settings":
      return "#/settings";
    case "phone":
      return "#/phone";
    case "sessions":
      return "#/sessions";
    case "session":
      return `#/session/${route.id}${route.at !== undefined ? `@${route.at}` : ""}`;
    case "search":
      return "#/search";
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
