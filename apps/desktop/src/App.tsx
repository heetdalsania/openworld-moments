// SPDX-License-Identifier: AGPL-3.0-or-later
import { getCurrentWebview } from "@tauri-apps/api/webview";
import { useCallback, useEffect, useState } from "react";
import { type AppInfo, fetchAppInfo } from "./appInfo";
import { AssetView } from "./AssetView";
import { ImportPanel } from "./ImportPanel";
import { JobCenter } from "./JobCenter";
import { isActive, useJobFeed, useJobs } from "./jobs";
import { LibraryView } from "./LibraryView";
import { PhoneImport } from "./PhoneImport";
import { type Route, routeHref, useRoute } from "./route";
import { WatchedFolders } from "./WatchedFolders";
import type { WatchedFolderView } from "./watched";
import { XboxOnboarding } from "./XboxOnboarding";
import { describeWorker, fetchWorkerStatus, onWorkerStatus, type WorkerStatus } from "./worker";

function useWorkerStatus(): WorkerStatus | null {
  const [worker, setWorker] = useState<WorkerStatus | null>(null);
  useEffect(() => {
    let cancelled = false;
    const unlisten = onWorkerStatus((status) => {
      if (!cancelled) setWorker(status);
    });
    fetchWorkerStatus()
      .then((status) => {
        if (!cancelled) setWorker(status);
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

function SettingsView({ workerReady }: { workerReady: boolean }) {
  const [folders, setFolders] = useState<WatchedFolderView[] | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const onFolders = useCallback((views: WatchedFolderView[]) => setFolders(views), []);
  const hasXbox = folders?.some((v) => v.folder.source_kind === "xbox") ?? true;
  return (
    <section className="view" aria-labelledby="settings-heading">
      <h1 id="settings-heading">Settings</h1>
      {workerReady ? (
        <>
          {!hasXbox && <XboxOnboarding onAdded={() => setRefreshKey((k) => k + 1)} />}
          <WatchedFolders onChange={onFolders} refreshKey={refreshKey} />
        </>
      ) : (
        <p role="status">Settings are available once the media worker is running.</p>
      )}
    </section>
  );
}

function NavLink({ route, current, children }: { route: Route; current: Route; children: string }) {
  const active =
    current.view === route.view || (route.view === "library" && current.view === "asset");
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

export function App() {
  const route = useRoute();
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
      <a className="skip" href="#main">
        Skip to content
      </a>
      <header className="topbar">
        <span className="brand">OpenWorld Moments</span>
        <nav aria-label="Primary">
          <NavLink route={{ view: "library" }} current={route}>
            Library
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
      <div className="body">
        <main id="main" tabIndex={-1}>
          {route.view === "library" &&
            (ready ? (
              <LibraryView onImport={openImport} />
            ) : (
              <section className="view">
                <h1>Library</h1>
                <p role="status">The library opens once the media worker is running.</p>
              </section>
            ))}
          {route.view === "asset" && ready && <AssetView key={route.id} id={route.id} />}
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
