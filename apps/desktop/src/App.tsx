// SPDX-License-Identifier: AGPL-3.0-or-later
import { getCurrentWebview } from "@tauri-apps/api/webview";
import { useCallback, useEffect, useState } from "react";
import { Announcer } from "./Announcer";
import { describeError, revealLibrary } from "./api";
import { AppearanceSettings } from "./AppearanceSettings";
import { LibraryLocation } from "./LibraryLocation";
import { type AppInfo, fetchAppInfo } from "./appInfo";
import { DiagnosticsPanel } from "./DiagnosticsPanel";
import { GUIDES_URL, Onboarding } from "./Onboarding";
import { applyAppearance, getPreferences, setOnboarding, usePreferences } from "./preferences";
import { PrivacyChoices } from "./PrivacyChoices";
import { useAction } from "./query";
import { CalibrationView } from "./CalibrationView";
import { EditorView } from "./EditorView";
import { ProjectsView } from "./ProjectsView";
import { hasUnsavedProjects } from "./projectWorkspace";
import { AssetView } from "./AssetView";
import { ImportPanel } from "./ImportPanel";
import { JobCenter } from "./JobCenter";
import { isActive, useJobFeed, useJobs } from "./jobs";
import { LibraryView } from "./LibraryView";
import { PhoneImport } from "./PhoneImport";
import { navigate, type Route, routeHref, useRoute } from "./route";
import { SessionsView } from "./SessionsView";
import { SearchView } from "./SearchView";
import { SessionView } from "./SessionView";
import { WatchedFolders } from "./WatchedFolders";
import type { WatchedFolderView } from "./watched";
import { ModelManager } from "./ModelManager";
import { SystemPanel } from "./SystemPanel";
import { XboxOnboarding } from "./XboxOnboarding";
import { describeWorker, fetchWorkerStatus, onWorkerStatus, type WorkerStatus } from "./worker";

function useWorkerStatus(): WorkerStatus | null {
  const [worker, setWorker] = useState<WorkerStatus | null>(null);
  useEffect(() => {
    let cancelled = false;
    let receivedEvent = false;
    const unlisten = onWorkerStatus((status) => {
      receivedEvent = true;
      if (!cancelled) setWorker(status);
    });
    // Register before reading the snapshot, and keep newer live status if its
    // event arrives while the initial request is still resolving.
    unlisten
      .then(() => fetchWorkerStatus())
      .then((status) => {
        if (!cancelled && !receivedEvent) setWorker(status);
      })
      .catch(() => {
        // The host reports worker problems through the status itself.
      });
    return () => {
      cancelled = true;
      void unlisten.then((stop) => stop());
    };
  }, []);
  return worker;
}

function useHostInfo(): AppInfo | null {
  const [info, setInfo] = useState<AppInfo | null>(null);
  useEffect(() => {
    let cancelled = false;
    fetchAppInfo()
      .then((value) => {
        if (!cancelled) setInfo(value);
      })
      .catch(() => {
        // The footer simply omits the version.
      });
    return () => {
      cancelled = true;
    };
  }, []);
  return info;
}

/** Paths dropped onto the window, and whether something is being dragged over it. */
function useDroppedPaths(onDrop: (paths: string[]) => void): boolean {
  const [over, setOver] = useState(false);
  useEffect(() => {
    let stop: (() => void) | undefined;
    let cancelled = false;
    getCurrentWebview()
      .onDragDropEvent((event) => {
        const payload = event.payload;
        if (payload.type === "over" || payload.type === "enter") setOver(true);
        else if (payload.type === "leave") setOver(false);
        else if (payload.type === "drop") {
          setOver(false);
          if (payload.paths.length) onDrop(payload.paths);
        }
      })
      .then((unlisten) => {
        if (cancelled) unlisten();
        else stop = unlisten;
      })
      .catch(() => {
        // Outside the desktop shell (tests, browser preview) there are no drop events.
      });
    return () => {
      cancelled = true;
      stop?.();
    };
  }, [onDrop]);
  return over;
}

function HelpPanel({ workerReady }: { workerReady: boolean }) {
  const library = useAction(revealLibrary);
  return (
    <section className="panel" aria-labelledby="help-heading">
      <h2 id="help-heading">Help and setup</h2>
      <p>
        Guides for Xbox, PlayStation, watched folders, capture cards, troubleshooting and known
        limitations are in the project documentation: <span className="url">{GUIDES_URL}</span>
      </p>
      <div className="row">
        <button type="button" onClick={() => setOnboarding("pending")}>
          Run setup again
        </button>
        <button
          type="button"
          disabled={!workerReady || library.busy}
          onClick={() => void library.run()}
        >
          Show library folder
        </button>
      </div>
      {library.error && <p role="alert">{describeError(library.error)}</p>}
    </section>
  );
}

function SettingsView({ workerReady }: { workerReady: boolean }) {
  const [folders, setFolders] = useState<WatchedFolderView[] | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const onFolders = useCallback((views: WatchedFolderView[]) => setFolders(views), []);
  const hasXbox = folders?.some((v) => v.folder.source_kind === "xbox") ?? true;
  return (
    <section className="view" aria-labelledby="settings-heading">
      <h1 id="settings-heading">Settings</h1>
      <PrivacyChoices />
      <LibraryLocation />
      {workerReady ? (
        <>
          <SystemPanel />
          <ModelManager />
          {!hasXbox && <XboxOnboarding onAdded={() => setRefreshKey((k) => k + 1)} />}
          <p>
            <a href="#/calibration">Calibrate detector profile regions</a>
          </p>
          <WatchedFolders onChange={onFolders} refreshKey={refreshKey} />
        </>
      ) : (
        <p role="status">
          System checks, models and watched folders are available once the media worker is running.
        </p>
      )}
      <AppearanceSettings />
      <DiagnosticsPanel workerReady={workerReady} />
      <HelpPanel workerReady={workerReady} />
    </section>
  );
}

function NavLink({ route, current, children }: { route: Route; current: Route; children: string }) {
  const active =
    current.view === route.view ||
    (route.view === "projects" && current.view === "project") ||
    (route.view === "library" && current.view === "asset") ||
    (route.view === "sessions" && current.view === "session") ||
    (route.view === "settings" && current.view === "calibration");
  return (
    <a href={routeHref(route)} aria-current={active ? "page" : undefined}>
      {children}
    </a>
  );
}

function WorkerBanner({ worker }: { worker: WorkerStatus | null }) {
  if (worker?.status === "ready") return null;
  const failed = worker?.status === "failed";
  return (
    <div className={`banner ${failed ? "warn" : ""}`} role={failed ? "alert" : "status"}>
      {describeWorker(worker)}
      {worker?.status === "restarting" && " Your jobs are kept and continue afterwards."}
    </div>
  );
}

function Routes({
  route,
  ready,
  openImport,
}: {
  route: Route;
  ready: boolean;
  openImport: () => void;
}) {
  return (
    <>
      {route.view === "library" &&
        (ready ? (
          <LibraryView onImport={openImport} />
        ) : (
          <section className="view">
            <h1>Library</h1>
            <p role="status">The library opens once the media worker is running.</p>
          </section>
        ))}
      {route.view === "asset" && ready && (
        <AssetView
          key={route.id}
          id={route.id}
          {...(route.at !== undefined ? { at: route.at } : {})}
        />
      )}
      {route.view === "sessions" &&
        (ready ? (
          <SessionsView />
        ) : (
          <section className="view">
            <h1>Sessions</h1>
            <p role="status">Sessions open once the media worker is running.</p>
          </section>
        ))}
      {route.view === "session" && ready && (
        <SessionView
          key={route.id}
          id={route.id}
          {...(route.at !== undefined ? { at: route.at } : {})}
        />
      )}
      {route.view === "projects" && <ProjectsView workerReady={ready} />}
      {route.view === "project" && <EditorView key={route.id} id={route.id} workerReady={ready} />}
      {route.view === "search" && <SearchView workerReady={ready} />}
      {route.view === "calibration" && ready && <CalibrationView />}
      {route.view === "settings" && <SettingsView workerReady={ready} />}
      {route.view === "phone" &&
        (ready ? (
          <PhoneImport />
        ) : (
          <section className="view">
            <h1>Import from phone</h1>
            <p role="status">Available once the media worker is running.</p>
          </section>
        ))}
    </>
  );
}

export function App() {
  const route = useRoute();
  const prefs = usePreferences();
  useEffect(() => applyAppearance(getPreferences().appearance), []);
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (hasUnsavedProjects()) event.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, []);
  // "/" or Ctrl/Cmd+K opens Search from anywhere except while typing.
  useEffect(() => {
    const open = (event: globalThis.KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const typing =
        target instanceof HTMLInputElement ||
        target instanceof HTMLTextAreaElement ||
        target instanceof HTMLSelectElement ||
        Boolean(target?.isContentEditable);
      const slash =
        event.key === "/" && !typing && !event.metaKey && !event.ctrlKey && !event.altKey;
      const command = event.key.toLowerCase() === "k" && (event.metaKey || event.ctrlKey);
      if (!slash && !command) return;
      event.preventDefault();
      if (window.location.hash === routeHref({ view: "search" })) {
        document.getElementById("search-input")?.focus();
      } else {
        navigate({ view: "search" });
      }
    };
    window.addEventListener("keydown", open);
    return () => window.removeEventListener("keydown", open);
  }, []);
  const worker = useWorkerStatus();
  const info = useHostInfo();
  const ready = worker?.status === "ready";
  useJobFeed(ready);
  const { jobs } = useJobs();
  const activeJobs = jobs.filter((j) => isActive(j) && j.kind !== "diagnostic").length;
  const [jobsOpen, setJobsOpen] = useState(false);
  const [importPaths, setImportPaths] = useState<string[] | null>(null);
  const openImport = useCallback(() => setImportPaths([]), []);
  const onDrop = useCallback((paths: string[]) => setImportPaths(paths), []);
  const dragging = useDroppedPaths(onDrop);

  return (
    <div className="app">
      <a
        className="skip"
        href="#main"
        onClick={(event) => {
          event.preventDefault();
          document.getElementById("main")?.focus();
        }}
      >
        Skip to content
      </a>
      <header className="topbar">
        <span className="brand">OpenWorld Moments</span>
        <nav aria-label="Primary">
          <NavLink route={{ view: "library" }} current={route}>
            Library
          </NavLink>
          <NavLink route={{ view: "sessions" }} current={route}>
            Sessions
          </NavLink>
          <NavLink route={{ view: "projects" }} current={route}>
            Projects
          </NavLink>
          <NavLink route={{ view: "search" }} current={route}>
            Search
          </NavLink>
          <NavLink route={{ view: "settings" }} current={route}>
            Settings
          </NavLink>
        </nav>
        <div className="actions">
          <button type="button" className="primary" onClick={openImport} disabled={!ready}>
            Import
          </button>
          <a
            className="button"
            href={routeHref({ view: "phone" })}
            aria-current={route.view === "phone" ? "page" : undefined}
          >
            Import from phone
          </a>
          <button
            type="button"
            aria-expanded={jobsOpen}
            aria-controls="job-center"
            onClick={() => setJobsOpen((open) => !open)}
          >
            Background jobs{activeJobs > 0 ? ` (${activeJobs} running)` : ""}
          </button>
        </div>
      </header>
      <WorkerBanner worker={worker} />
      <Announcer />
      <div className="body">
        <main id="main" tabIndex={-1}>
          {prefs.onboarding === "pending" ? (
            <Onboarding workerReady={ready} onImport={openImport} />
          ) : (
            <Routes route={route} ready={ready} openImport={openImport} />
          )}
        </main>
        {jobsOpen && (
          <div id="job-center">
            <JobCenter onClose={() => setJobsOpen(false)} />
          </div>
        )}
      </div>
      <footer className="footer">
        <span>{info ? `Version ${info.version} (${info.stage})` : ""}</span>
        <span>
          Unofficial community project. Not affiliated with or endorsed by Rockstar Games.
        </span>
      </footer>
      {dragging && importPaths === null && (
        <div className="drop-hint" aria-hidden="true">
          Drop videos or folders to import
        </div>
      )}
      {importPaths !== null && (
        <ImportPanel
          initialPaths={importPaths}
          onClose={() => setImportPaths(null)}
          onStarted={() => setJobsOpen(true)}
        />
      )}
    </div>
  );
}
