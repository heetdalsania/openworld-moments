// SPDX-License-Identifier: AGPL-3.0-or-later
// Test double for the desktop host: routes `worker_api` calls to handlers, records
// them, and lets tests emit host events (job events, resync, worker status).
import { vi } from "vitest";
import type { Job, MediaAsset } from "../api";

export type Handler = (body: unknown) => unknown;
type Listener = (event: { payload: unknown }) => void;

export interface FakeHost {
  routes: Map<string, Handler>;
  calls: { method: string; path: string; body: unknown }[];
  listeners: Map<string, Listener[]>;
  worker: unknown;
  /** The `platform_info` answer (M33); a Windows x64 alpha build by default. */
  platform: unknown;
  emit: (name: string, payload: unknown) => void;
  route: (key: string, handler: Handler | unknown) => void;
  posts: (path: string) => unknown[];
}

export function createHost(): FakeHost {
  const host: FakeHost = {
    routes: new Map(),
    calls: [],
    listeners: new Map(),
    worker: { status: "ready", port: 1, pid: 1, restarts: 0 },
    platform: windowsPlatform(),
    emit(name, payload) {
      for (const listener of host.listeners.get(name) ?? []) listener({ payload });
    },
    route(key, handler) {
      host.routes.set(key, typeof handler === "function" ? (handler as Handler) : () => handler);
    },
    posts(path) {
      return host.calls.filter((c) => c.method === "POST" && c.path === path).map((c) => c.body);
    },
  };
  return host;
}

export function windowsPlatform(): Record<string, unknown> {
  return {
    schema_version: "1.25",
    host_version: "0.1.0",
    os: { family: "windows", version: null, minimum: null },
    architecture: { binary: "x86_64", translated: null },
    build: { target: "x86_64-pc-windows-msvc", profile: "release", bundled_worker: true },
    support: { level: "alpha", reasons: [] },
    directories: { convention: "windows-appdata" },
    integrations: { file_manager: "explorer", secret_store: "none", menus: "default" },
  };
}

/** Wire `host` into the mocked Tauri modules. */
export function install(
  host: FakeHost,
  mocks: { invoke: ReturnType<typeof vi.fn>; listen: ReturnType<typeof vi.fn> },
): void {
  mocks.invoke.mockImplementation((command: string, args?: Record<string, unknown>) => {
    if (command === "app_info") {
      return Promise.resolve({ name: "OpenWorld Moments", version: "0.0.0", stage: "planning" });
    }
    if (command === "platform_info") return Promise.resolve(host.platform);
    if (command === "worker_status") return Promise.resolve(host.worker);
    if (command === "watched_folders_list") return Promise.resolve({ folders: [], status: [] });
    if (command === "worker_api") {
      const method = String(args?.method);
      const path = String(args?.path);
      host.calls.push({ method, path, body: args?.body });
      const key = `${method} ${path}`;
      const handler =
        host.routes.get(key) ??
        [...host.routes.entries()].find(
          ([k]) => k.endsWith("*") && key.startsWith(k.slice(0, -1)),
        )?.[1];
      if (!handler) {
        return Promise.reject({
          code: "test.no_route",
          message: `no route ${key}`,
          retryable: false,
        });
      }
      try {
        return Promise.resolve(handler(args?.body));
      } catch (error) {
        return Promise.reject(error);
      }
    }
    return Promise.reject(new Error(`unexpected command ${command}`));
  });
  mocks.listen.mockImplementation((name: string, listener: Listener) => {
    host.listeners.set(name, [...(host.listeners.get(name) ?? []), listener]);
    return Promise.resolve(() => {
      host.listeners.set(
        name,
        (host.listeners.get(name) ?? []).filter((l) => l !== listener),
      );
    });
  });
}

/** The value, or a clear test failure when it is missing. */
export function must<T>(value: T | null | undefined, what = "value"): T {
  if (value === null || value === undefined) throw new Error(`expected ${what}`);
  return value;
}

export const ASSET_ID = "ast_01JCBQ00000000000000000001";

export function asset(overrides: Partial<MediaAsset> = {}): MediaAsset {
  return {
    schema_version: "1.6",
    id: ASSET_ID,
    sha256: "3f".repeat(32),
    original_name: "Heist finale.mp4",
    source_kind: "xbox",
    import_mode: "reference",
    duration_ms: 61_500,
    container: "mov,mp4,m4a,3gp,3g2,mj2",
    video: {
      codec: "h264",
      width: 1920,
      height: 1080,
      frame_rate: { num: 60, den: 1 },
      pixel_format: "yuv420p",
      color: { hdr: false },
    },
    audio: [{ codec: "aac", channels: 2, sample_rate_hz: 48_000 }],
    created_at: "2026-11-21T09:00:00Z",
    ...overrides,
  } as MediaAsset;
}

let jobCounter = 0;

export function job(overrides: Partial<Job> = {}): Job {
  jobCounter += 1;
  return {
    schema_version: "1.6",
    id: `job_01JCBQ000000000000000000${String(jobCounter).padStart(2, "0")}`,
    kind: "import",
    state: "queued",
    created_at: `2026-11-21T09:00:${String(jobCounter % 60).padStart(2, "0")}Z`,
    ...overrides,
  } as Job;
}
