// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * M38: what the native macOS menu items do (the host builds the menus in
 * `src-tauri/src/menu.rs` and sends each app action here by ID), File ▸ Open Recent,
 * and the unsaved-work flag Quit checks.
 *
 * Windows has no menu bar; nothing here changes its in-app shortcuts.
 */
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { useEffect, useRef } from "react";
import { revealLibrary, toApiError } from "./api";
import { getPreferences, setAppearance, setOnboarding, TEXT_SIZES } from "./preferences";
import { hasUnsavedProjects, subscribeWorkspaces } from "./projectWorkspace";
import { navigate, routeHref } from "./route";

export const MENU_EVENT = "menu://action";

export interface MenuHandlers {
  /** Whether the media worker is ready (Import needs it). */
  ready: boolean;
  openImport: () => void;
  openJobs: () => void;
  openShortcuts: () => void;
  /** Tell the user something the action could not do. */
  report: (message: string) => void;
}

/** Open Search, or focus its box when Search is already showing. */
export function openSearch(): void {
  if (window.location.hash === routeHref({ view: "search" })) {
    document.getElementById("search-input")?.focus();
  } else {
    navigate({ view: "search" });
  }
}

/** After navigating, move focus to the element with `id` once it has rendered. */
export function focusWhenShown(id: string, attempts = 20): void {
  const element = document.getElementById(id);
  if (element) {
    element.focus();
    element.scrollIntoView?.({ block: "start" });
  } else if (attempts > 0) {
    window.setTimeout(() => focusWhenShown(id, attempts - 1), 50);
  }
}

function stepTextSize(direction: 1 | -1 | 0): void {
  if (direction === 0) {
    setAppearance({ textSize: 100 });
    return;
  }
  const sizes = [...TEXT_SIZES];
  const index = sizes.indexOf(getPreferences().appearance.textSize);
  const next = sizes[Math.min(sizes.length - 1, Math.max(0, index + direction))];
  if (next !== undefined) setAppearance({ textSize: next });
}

/** Perform a menu action. Returns false for an ID this UI does not know. */
export function runMenuAction(id: string, handlers: MenuHandlers): boolean {
  if (id.startsWith("recent:")) {
    const project = id.slice("recent:".length);
    if (!/^prj_[0-9A-HJKMNP-TV-Z]{26}$/.test(project)) return false;
    navigate({ view: "project", id: project });
    return true;
  }
  switch (id) {
    case "app.settings":
      navigate({ view: "settings" });
      return true;
    case "file.import":
      if (handlers.ready) handlers.openImport();
      else handlers.report("Import is available once the media worker is running.");
      return true;
    case "file.phone":
      navigate({ view: "phone" });
      return true;
    case "file.new_project":
      // Projects start from a session range (M22).
      navigate({ view: "sessions" });
      focusWhenShown("sessions-heading");
      return true;
    case "file.recent_clear":
      clearRecentProjects();
      return true;
    case "file.reveal_library":
      revealLibrary().catch((error: unknown) => handlers.report(toApiError(error).message));
      return true;
    case "edit.find":
      openSearch();
      return true;
    case "view.library":
      navigate({ view: "library" });
      return true;
    case "view.sessions":
      navigate({ view: "sessions" });
      return true;
    case "view.projects":
      navigate({ view: "projects" });
      return true;
    case "view.search":
      openSearch();
      return true;
    case "view.jobs":
      handlers.openJobs();
      return true;
    case "view.text_bigger":
      stepTextSize(1);
      return true;
    case "view.text_smaller":
      stepTextSize(-1);
      return true;
    case "view.text_actual":
      stepTextSize(0);
      return true;
    case "help.shortcuts":
      handlers.openShortcuts();
      return true;
    case "help.diagnostics":
      navigate({ view: "settings" });
      focusWhenShown("diagnostics-heading");
      return true;
    case "help.setup":
      setOnboarding("pending");
      return true;
    default:
      return false;
  }
}

/** Listen for native menu actions for as long as the component is mounted. */
export function useMenuActions(handlers: MenuHandlers): void {
  const latest = useRef(handlers);
  useEffect(() => {
    latest.current = handlers;
  });
  useEffect(() => {
    let stop: (() => void) | undefined;
    let cancelled = false;
    listen<string>(MENU_EVENT, (event) => {
      if (typeof event.payload === "string") runMenuAction(event.payload, latest.current);
    })
      .then((unlisten) => {
        if (cancelled) unlisten();
        else stop = unlisten;
      })
      .catch(() => {
        // Outside the desktop shell there is no menu.
      });
    return () => {
      cancelled = true;
      stop?.();
    };
  }, []);
}

// -- Open Recent ---------------------------------------------------------------------

export const RECENT_KEY = "owm.recent-projects.v1";
export const RECENT_LIMIT = 10;

export interface RecentProject {
  id: string;
  title: string;
}

/** Recently opened projects, newest first. Unreadable storage means none. */
export function recentProjects(): RecentProject[] {
  try {
    const parsed: unknown = JSON.parse(window.localStorage.getItem(RECENT_KEY) ?? "[]");
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter(
        (p): p is RecentProject =>
          typeof p === "object" &&
          p !== null &&
          typeof (p as RecentProject).id === "string" &&
          /^prj_[0-9A-HJKMNP-TV-Z]{26}$/.test((p as RecentProject).id) &&
          typeof (p as RecentProject).title === "string",
      )
      .slice(0, RECENT_LIMIT);
  } catch {
    return [];
  }
}

function saveRecent(list: RecentProject[]): void {
  try {
    window.localStorage.setItem(RECENT_KEY, JSON.stringify(list));
  } catch {
    // The menu still updates for this session.
  }
  syncRecentMenu(list);
}

/** Put a project at the top of Open Recent. */
export function rememberProject(id: string, title: string): void {
  const rest = recentProjects().filter((p) => p.id !== id);
  saveRecent([{ id, title: title.slice(0, 200) }, ...rest].slice(0, RECENT_LIMIT));
}

/** Forget a project (for example after it was deleted). */
export function forgetProject(id: string): void {
  saveRecent(recentProjects().filter((p) => p.id !== id));
}

export function clearRecentProjects(): void {
  saveRecent([]);
}

/** Send the list to the native menu. Harmless where there is no menu. */
export function syncRecentMenu(list: RecentProject[] = recentProjects()): void {
  invoke("menu_recent_set", { projects: list }).catch(() => {
    // No host (tests, browser preview) or no menu: nothing to update.
  });
}

// -- Quit ------------------------------------------------------------------------------

/** Keep the host's unsaved-work flag current, so Quit asks before losing edits. */
export function useQuitGuard(): void {
  useEffect(() => {
    let last: boolean | null = null;
    const update = () => {
      const unsaved = hasUnsavedProjects();
      if (unsaved === last) return;
      last = unsaved;
      invoke("quit_guard_set", { unsaved }).catch(() => {
        // No host: nothing to tell.
      });
    };
    update();
    return subscribeWorkspaces(update);
  }, []);
}

// -- Guides and System Settings ---------------------------------------------------------

export type GuideTopic =
  | "index"
  | "macos"
  | "macos-install"
  | "macos-permissions"
  | "macos-troubleshooting"
  | "accessibility"
  | "diagnostics"
  | "phone";

/** Open a user guide in the browser (the host maps the topic to a fixed page). */
export async function openGuide(topic: GuideTopic): Promise<void> {
  try {
    await invoke("guide_open", { topic });
  } catch (error) {
    throw toApiError(error);
  }
}

export type SettingsPane = "files-and-folders" | "local-network";

/** Open the System Settings pane where access is granted (macOS). */
export async function openSystemSettings(pane: SettingsPane): Promise<void> {
  try {
    await invoke("system_settings_open", { pane });
  } catch (error) {
    throw toApiError(error);
  }
}
