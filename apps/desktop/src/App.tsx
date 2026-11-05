// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from "react";
import { type AppInfo, fetchAppInfo } from "./appInfo";
import { describeWorker, fetchWorkerStatus, onWorkerStatus, type WorkerStatus } from "./worker";

type HostState =
  { status: "loading" } | { status: "ready"; info: AppInfo } | { status: "error"; message: string };

export function App() {
  const [host, setHost] = useState<HostState>({ status: "loading" });
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

  useEffect(() => {
    let cancelled = false;
    fetchAppInfo()
      .then((info) => {
        if (!cancelled) setHost({ status: "ready", info });
      })
      .catch((error: unknown) => {
        if (!cancelled) setHost({ status: "error", message: String(error) });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main className="placeholder">
      <h1>OpenWorld Moments</h1>
      <p className="stage">Planning stage — no product features yet.</p>
      <p>
        This window confirms the desktop shell builds and runs. Import, sessions, and editing arrive
        in later milestones.
      </p>
      <p className="host" role="status">
        {host.status === "loading" && "Connecting to desktop host…"}
        {host.status === "ready" && `Desktop host ${host.info.version} (${host.info.stage})`}
        {host.status === "error" && `Desktop host unavailable: ${host.message}`}
      </p>
      <p className="host" data-testid="worker-status">
        {describeWorker(worker)}
      </p>
      <p className="notice">
        Unofficial community project. Not affiliated with or endorsed by Rockstar Games.
      </p>
    </main>
  );
}
