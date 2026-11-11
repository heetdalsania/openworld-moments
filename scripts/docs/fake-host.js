// SPDX-License-Identifier: AGPL-3.0-or-later
/* global window */
// Documentation screenshots (M31): a stand-in for the desktop host so the real UI can be
// rendered in a browser with synthetic data only. No real worker, library, footage or
// paths are involved. Injected before the page loads by capture-screenshots.py.
(() => {
  const asset = (n, name, minutes, kind) => ({
    schema_version: "1.6",
    id: `ast_01JCBQ${String(n).padStart(20, "0")}`,
    sha256: String(n).repeat(64).slice(0, 64),
    original_name: name,
    source_kind: kind,
    import_mode: "reference",
    duration_ms: Math.round(minutes * 60_000),
    container: "mov,mp4,m4a,3gp,3g2,mj2",
    video: {
      codec: "h264",
      width: 1920,
      height: 1080,
      frame_rate: { num: 60, den: 1 },
      pixel_format: "yuv420p",
      color: { hdr: false },
    },
    audio: [{ codec: "aac", channels: 2, sample_rate_hz: 48000 }],
    created_at: `2026-11-10T19:0${n}:00Z`,
  });
  const assets = [
    asset(1, "Synthetic capture - night drive.mp4", 4.5, "xbox"),
    asset(2, "Synthetic capture - harbor chase.mp4", 2.2, "playstation"),
    asset(3, "Synthetic capture - rooftop.mp4", 1.1, "capture_card"),
  ];
  const doctor = {
    schema_version: "1.23",
    ready: true,
    packaged: true,
    platform: "Windows",
    architecture: "AMD64",
    free_bytes: 182 * 1024 ** 3,
    checks: [
      {
        id: "storage",
        status: "pass",
        message: "Keep at least 512 MiB free; imports, models and renders need additional space.",
      },
      {
        id: "permissions",
        status: "pass",
        message:
          "The library must allow temporary files. Choose a writable local folder if this fails.",
      },
      {
        id: "loopback",
        status: "pass",
        message: "Allow local loopback ports in security software. Phone LAN is off by default.",
      },
      {
        id: "sqlite",
        status: "pass",
        message:
          "SQLite 3.42 or newer with FTS5 is required. Repair the bundled runtime if unavailable.",
      },
      {
        id: "codecs",
        status: "pass",
        message:
          "FFmpeg needs libx264, AAC, JPEG and proxy filters. Repair packaged tools if missing.",
      },
      {
        id: "cpu-encode",
        status: "pass",
        message: "The CPU test encode must pass. Repair packaged tools if it fails.",
      },
      {
        id: "acceleration",
        status: "warn",
        message: "Hardware needs a test encode. CPU libx264 is the fallback when unavailable.",
      },
      {
        id: "models",
        status: "pass",
        message: "Catalog signature required. Repair the app on failure. Downloads are explicit.",
      },
    ],
    tools: [{ name: "FFmpeg", version: "9.0.2", origin: "bundle", license: "GPL-2.0-or-later" }],
  };
  const report = {
    schema_version: "1.24",
    generated_at: "2026-11-11T12:00:00Z",
    worker: { api_version: "1", schema_version: "1.24", worker_version: "0.1.0" },
    system: {
      available: true,
      ready: true,
      packaged: true,
      platform: "Windows",
      architecture: "AMD64",
      free_mib: 186368,
      checks: doctor.checks.map(({ id, status }) => ({ id, status, message: "…" })),
      tools: [{ name: "FFmpeg", version: "9.0.2", origin: "bundle" }],
    },
    library: {
      clips: 3,
      sessions: 1,
      projects: 1,
      renders: 1,
      watched_folders: 1,
      collections: 0,
      event_observations: 12,
      transcript_segments: 0,
      database_schema: 19,
    },
    models: [
      { name: "tiny.en", revision: "5359861c739e955e79d9a303bcbc70fb988958b1", installed: false },
    ],
    jobs: {
      totals: [
        { kind: "import", state: "ready", count: 3 },
        { kind: "probe", state: "failed", count: 1 },
      ],
      recent_failures: [
        { kind: "probe", code: "probe.unreadable", retryable: false, date: "2026-11-10" },
      ],
    },
    privacy: {
      footage: "never included",
      file_names: "removed",
      paths: "removed",
      tokens: "removed",
      failure_messages: "omitted",
    },
  };
  const models = {
    schema_version: "1.23",
    catalog_version: 1,
    models: [
      {
        name: "tiny.en",
        revision: "5359861c739e955e79d9a303bcbc70fb988958b1",
        size_bytes: 77704715,
        sha256: "921e4cf8686fdd993dcd081a5da5b6c365bfde1162e72b08d75ac75289920b1f",
        license: "MIT",
        source_url: "https://huggingface.co/ggerganov/whisper.cpp",
        downloaded_bytes: 0,
        disk_required_bytes: 77704715,
        active_sha256: null,
        versions: [],
      },
    ],
  };
  const api = {
    "GET /v1/system-doctor": () => doctor,
    "GET /v1/model-manager": () => models,
    "GET /v1/jobs?limit=200": () => [],
    "GET /v1/projects": () => [],
    "POST /v1/diagnostics": () => ({
      report,
      content: JSON.stringify(report, null, 2) + "\n",
      filename: "openworld-moments-diagnostics-20261111.json",
    }),
  };
  const callbacks = new Map();
  let nextCallback = 1;
  const commands = {
    app_info: () => ({
      name: "OpenWorld Moments",
      version: "0.1.0-alpha.31",
      stage: "documentation screenshot",
    }),
    worker_status: () => ({ status: "ready", port: 1, pid: 1, restarts: 0 }),
    worker_list_jobs: () => [],
    watched_folders_list: () => ({ folders: [], status: [] }),
    phone_interfaces: () => [{ name: "Wi-Fi", address: "192.168.1.20" }],
    phone_status: () => ({ state: "idle", uploads: [] }),
    phone_stop: () => ({ state: "idle", uploads: [] }),
    worker_api: ({ method, path }) => {
      const key = `${method} ${path}`;
      if (api[key]) return api[key]();
      if (key.startsWith("GET /v1/assets?")) return assets;
      if (key.startsWith("GET /v1/sessions")) return [];
      throw {
        code: "request.not_found",
        message: `No synthetic data for ${key}`,
        retryable: false,
      };
    },
    "plugin:event|listen": () => nextCallback++,
    "plugin:event|unlisten": () => null,
  };
  window.__TAURI_INTERNALS__ = {
    metadata: {
      currentWindow: { label: "main" },
      currentWebview: { windowLabel: "main", label: "main" },
    },
    transformCallback(callback) {
      const id = nextCallback++;
      callbacks.set(id, callback);
      return id;
    },
    unregisterCallback(id) {
      callbacks.delete(id);
    },
    convertFileSrc: (path) => path,
    invoke(command, args) {
      const handler = commands[command];
      if (!handler)
        return Promise.reject({
          code: "app.error",
          message: `Not available in screenshots: ${command}`,
          retryable: false,
        });
      try {
        return Promise.resolve(handler(args ?? {}));
      } catch (error) {
        return Promise.reject(error);
      }
    },
  };
  window.__TAURI_EVENT_PLUGIN_INTERNALS__ = { unregisterListener: () => undefined };
})();
