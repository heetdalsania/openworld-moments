// SPDX-License-Identifier: AGPL-3.0-or-later
// Export panel (M24) through the fake host: render the saved revision, encoder
// availability and quality notes, explicit text omission, results with validation,
// an explicit CPU fallback after a hardware failure, and errors.
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { EditorProject } from "@openworld-moments/contracts";
import type { RenderRecord } from "./api";
import { ExportPanel, textNeedingOmission } from "./ExportPanel";
import { resetJobs, upsertJob } from "./jobs";
import { resetQueries } from "./query";
import { createHost, type FakeHost, install, job } from "./testing/fakeHost";

const invoke = vi.hoisted(() => vi.fn());
const listen = vi.hoisted(() => vi.fn());
vi.mock("@tauri-apps/api/core", () => ({ invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen }));

const PID = "prj_01JCBQ00000000000000000005";
const JOB = "job_01JCBQ00000000000000000041";
let host: FakeHost;
let renders: RenderRecord[];

function project(overrides: Partial<EditorProject["project"]> = {}): EditorProject {
  return {
    schema_version: "1.17",
    model_version: 1,
    project: {
      schema_version: "1.17",
      id: PID,
      title: "Escape",
      created_at: "2026-11-08T10:00:00Z",
      tracks: [{ kind: "video", segments: [] }],
      captions: [{ start_ms: 0, end_ms: 1000, text: "Go" }],
      overlays: [],
      audio: { gain_db: 0, mute_ranges: [] },
      ...overrides,
    },
    layout: { aspect_ratio: "16:9" },
    sources: [],
  } as EditorProject;
}

const preset = (id: string, name: string) => ({
  schema_version: "1.18",
  id,
  display_name: name,
  width: 1920,
  height: 1080,
  fps: { num: 30, den: 1 },
  video: { codec: "h264", crf: 20 },
  audio: { codec: "aac", bitrate_kbps: 192, sample_rate_hz: 48000 },
});

function readyRecord(): RenderRecord {
  return {
    schema_version: "1.18",
    id: JOB,
    project_id: PID,
    project_revision: 4,
    status: "ready",
    preset_id: "horizontal-1080p30",
    encoder: "libx264",
    created_at: "2026-11-08T10:00:00Z",
    finished_at: "2026-11-08T10:00:20Z",
    output: {
      relative_path: `renders/${PID}/${JOB}.mp4`,
      size_bytes: 12_400_000,
      sha256: "c".repeat(64),
      duration_ms: 64_000,
    },
    validation: {
      passed: true,
      checks: [
        { name: "duration", passed: true, detail: "64000 ms" },
        { name: "black_frames", passed: true, detail: "No unexpected black samples" },
      ],
      probe: { format: "mp4", duration_ms: 64_000, video_streams: 1, audio_streams: 1 },
      thresholds: { duration_tolerance_ms: 100, black_luma: 20, source_luma: 40 },
    },
  } as unknown as RenderRecord;
}

beforeEach(() => {
  renders = [];
  host = createHost();
  install(host, { invoke, listen });
  host.route("GET /v1/render/presets", [
    preset("horizontal-1080p30", "Horizontal 1080p, 30 fps"),
    preset("horizontal-720p30", "Horizontal 720p, 30 fps"),
  ]);
  host.route("GET /v1/render/encoders", {
    schema_version: "1.18",
    ffmpeg_version: "7.1.1",
    encoders: [
      { id: "libx264", label: "CPU (libx264)", kind: "cpu", available: true },
      {
        id: "h264_videotoolbox",
        label: "Apple VideoToolbox",
        kind: "hardware",
        available: true,
        quality_note: "VideoToolbox quality approximates x264 CRF.",
      },
      {
        id: "h264_nvenc",
        label: "NVIDIA NVENC",
        kind: "hardware",
        available: false,
        reason: "Not built into this FFmpeg.",
      },
    ],
  });
  host.route(`GET /v1/projects/${PID}/renders`, () => renders);
  host.route(`POST /v1/projects/${PID}/render`, (body: unknown) =>
    job({ kind: "render", state: "queued", params: { project_id: PID, ...(body as object) } }),
  );
});

afterEach(() => {
  cleanup();
  invoke.mockReset();
  listen.mockReset();
  resetQueries();
  resetJobs();
});

function panel(document = project(), flush = vi.fn(() => Promise.resolve())) {
  render(<ExportPanel projectId={PID} document={document} flush={flush} workerReady />);
  return flush;
}

describe("export panel", () => {
  it("saves pending edits, then renders with the chosen preset and encoder", async () => {
    const user = userEvent.setup();
    const order: string[] = [];
    const flush = vi.fn(() => {
      order.push("flush");
      return Promise.resolve();
    });
    host.route(`POST /v1/projects/${PID}/render`, (body: unknown) => {
      order.push("render");
      return job({
        kind: "render",
        state: "queued",
        params: { project_id: PID, ...(body as object) },
      });
    });
    panel(project(), flush);
    await screen.findByRole("option", { name: "Horizontal 720p, 30 fps" });
    await user.selectOptions(screen.getByRole("combobox", { name: /Preset/ }), "horizontal-720p30");
    await user.click(screen.getByRole("button", { name: "Render" }));
    expect(order).toEqual(["flush", "render"]);
    expect(host.posts(`/v1/projects/${PID}/render`)).toEqual([
      { preset_id: "horizontal-720p30", encoder: "libx264" },
    ]);
    expect(await screen.findByText(/Rendering/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Render" })).toHaveProperty("disabled", true);
  });

  it("only offers encoders that passed a test encode and shows hardware quality notes", async () => {
    const user = userEvent.setup();
    panel();
    const nvenc = await screen.findByRole("option", { name: "NVIDIA NVENC (unavailable)" });
    expect(nvenc).toHaveProperty("disabled", true);
    expect(screen.getByText("NVIDIA NVENC: Not built into this FFmpeg.")).toBeTruthy();
    await user.selectOptions(
      screen.getByRole("combobox", { name: /Encoder/ }),
      "h264_videotoolbox",
    );
    expect(screen.getByText("VideoToolbox quality approximates x264 CRF.")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Render" }));
    expect(host.posts(`/v1/projects/${PID}/render`)).toEqual([
      { preset_id: "horizontal-1080p30", encoder: "h264_videotoolbox" },
    ]);
  });

  it("requires an explicit choice to leave out text it cannot draw yet", async () => {
    const user = userEvent.setup();
    const document = project({
      overlays: [{ kind: "text", start_ms: 0, end_ms: 500, region: [0, 0, 1, 0.1], text: "Hi" }],
      caption_settings: {
        preset: "compact",
        region: [0.1, 0.8, 0.8, 0.1],
        burn_in: true,
        sidecar: "none",
      },
    });
    expect(textNeedingOmission(document)).toEqual(["text overlays", "burned-in captions"]);
    expect(textNeedingOmission(project())).toEqual([]);
    panel(document);
    const renderButton = await screen.findByRole("button", { name: "Render" });
    expect(renderButton).toHaveProperty("disabled", true);
    await user.click(
      screen.getByRole("checkbox", { name: "Render without text overlays and burned-in captions" }),
    );
    await user.click(renderButton);
    expect(host.posts(`/v1/projects/${PID}/render`)).toEqual([
      { preset_id: "horizontal-1080p30", encoder: "libx264", omit_text: true },
    ]);
  });

  it("shows a validated render with its library location", async () => {
    renders = [
      {
        ...readyRecord(),
        plan: { notes: ["HDR clips are tone-mapped to standard range (BT.709)."] },
      } as unknown as RenderRecord,
    ];
    panel();
    const list = await screen.findByRole("list", { name: "Renders" });
    expect(within(list).getByText(/1:04 · 12.4 MB · 2\/2 checks passed/)).toBeTruthy();
    expect(within(list).getByText(`renders/${PID}/${JOB}.mp4`)).toBeTruthy();
    expect(within(list).getByText(/revision 4/)).toBeTruthy();
    expect(within(list).getByText(/tone-mapped/)).toBeTruthy();
  });

  it("offers the CPU encoder after a hardware failure, never switching silently", async () => {
    renders = [
      {
        schema_version: "1.18",
        id: JOB,
        project_id: PID,
        status: "failed",
        preset_id: "horizontal-1080p30",
        encoder: "h264_videotoolbox",
        created_at: "2026-11-08T10:00:00Z",
        error: {
          code: "render.hardware_encoder_failed",
          message: "Apple VideoToolbox stopped during encoding.",
          retryable: true,
        },
        fallback: { encoder: "libx264", reason: "Apple VideoToolbox stopped during encoding." },
      } as RenderRecord,
    ];
    const user = userEvent.setup();
    panel();
    expect((await screen.findByRole("alert")).textContent).toContain("VideoToolbox stopped");
    expect(host.posts(`/v1/projects/${PID}/render`)).toEqual([]);
    await user.click(screen.getByRole("button", { name: "Render with the CPU encoder instead" }));
    expect(host.posts(`/v1/projects/${PID}/render`)).toEqual([
      { preset_id: "horizontal-1080p30", encoder: "libx264" },
    ]);
  });

  it("lists the checks a rejected render failed", async () => {
    renders = [
      {
        ...readyRecord(),
        status: "failed",
        output: undefined,
        error: {
          code: "render.validation_failed",
          message: "The rendered file failed validation and was not kept: duration",
          retryable: true,
        },
        validation: {
          ...readyRecord().validation,
          passed: false,
          checks: [{ name: "duration", passed: false, detail: "5600 ms (target 5000 ms)" }],
        },
      } as unknown as RenderRecord,
    ];
    panel();
    const failed = await screen.findByRole("list", { name: "Failed checks" });
    expect(failed.textContent).toContain("duration: 5600 ms (target 5000 ms)");
    expect(screen.getByRole("alert").textContent).toContain("was not kept");
  });

  it("refreshes the list when a render job finishes and explains refused requests", async () => {
    const user = userEvent.setup();
    host.route(`POST /v1/projects/${PID}/render`, () => {
      throw {
        code: "job.invalid_params",
        message: "A clip needs relinking first.",
        retryable: false,
      };
    });
    panel();
    await user.click(await screen.findByRole("button", { name: "Render" }));
    expect((await screen.findByRole("alert")).textContent).toContain("needs relinking");
    renders = [readyRecord()];
    const running = job({ kind: "render", state: "rendering", params: { project_id: PID } });
    upsertJob(running);
    upsertJob({ ...running, state: "ready" });
    expect(await screen.findByText(/checks passed/)).toBeTruthy();
  });
});
