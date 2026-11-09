// SPDX-License-Identifier: AGPL-3.0-or-later
// Optional local transcription panel (M18) through the fake host: privacy notice,
// missing engine and model guidance, transcribe and rebuild, seeking from a line,
// two-step deletion, progress and failures.
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SpeechModels, Transcript } from "./api";
import { resetJobs, upsertJob } from "./jobs";
import { resetQueries } from "./query";
import { createHost, type FakeHost, install, job } from "./testing/fakeHost";
import { TranscriptPanel } from "./TranscriptPanel";

const invoke = vi.hoisted(() => vi.fn());
const listen = vi.hoisted(() => vi.fn());
vi.mock("@tauri-apps/api/core", () => ({ invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen }));

const SES = "ses_01JCBQ00000000000000000001";
const AST = "ast_01JCBQ00000000000000000001";
let host: FakeHost;
let segments: Transcript["segments"];

const transcriber = {
  engine: "whisper.cpp" as const,
  engine_version: "1.7.6",
  engine_sha256: "a".repeat(64),
  model: "base.en",
  model_sha256: "b".repeat(64),
  transcriber_version: "1.0.0",
};

function line(id: number, start: number, text: string, confidence = 0.9) {
  return {
    id,
    asset_id: AST,
    start_ms: start,
    end_ms: start + 1500,
    source_start_ms: start,
    source_end_ms: start + 1500,
    text,
    language: "en",
    confidence,
    words: [],
    transcriber,
  };
}

function models(overrides: Partial<SpeechModels> = {}): SpeechModels {
  return {
    schema_version: "1.13",
    engine: { available: true, version: "1.7.6" },
    installed: [
      {
        name: "base.en",
        size_bytes: 147_964_211,
        sha256: "c".repeat(64),
        license: "MIT",
        installed_at: "2026-11-07T20:00:00Z",
      },
    ],
    catalog: [],
    ...overrides,
  };
}

beforeEach(() => {
  segments = [];
  host = createHost();
  install(host, { invoke, listen });
  host.route("GET /v1/transcription/models", () => models());
  host.route(`GET /v1/sessions/${SES}/transcript`, () => ({
    schema_version: "1.13",
    session_id: SES,
    segments,
  }));
  host.route(`POST /v1/sessions/${SES}/transcribe`, (body: unknown) =>
    job({ kind: "transcribe", state: "queued", params: { session_id: SES, ...(body as object) } }),
  );
  host.route(`DELETE /v1/sessions/${SES}/transcript`, () => {
    const deleted = segments.length;
    segments = [];
    return { deleted_segments: deleted };
  });
});

afterEach(() => {
  cleanup();
  invoke.mockReset();
  listen.mockReset();
  resetQueries();
  resetJobs();
});

function panel(onSeek = vi.fn()) {
  render(<TranscriptPanel sessionId={SES} onSeek={onSeek} />);
  return onSeek;
}

describe("transcript panel", () => {
  it("always explains that transcription is local, optional, and deletable", async () => {
    panel();
    const notice = await screen.findByText(/transcribed on this computer/);
    expect(notice.textContent).toContain("nothing is uploaded");
    expect(notice.textContent).toContain("only when you choose Install");
    expect(notice.textContent).toContain("without affecting your videos");
  });

  it("guides installation when the engine is missing, with no transcribe button", async () => {
    host.route("GET /v1/transcription/models", () =>
      models({
        engine: { available: false, reason: "Install whisper.cpp (whisper-cli) to enable it." },
        installed: [],
      }),
    );
    panel();
    expect(await screen.findByText(/Install whisper.cpp \(whisper-cli\)/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Transcribe/ })).toBeNull();
    expect(host.posts(`/v1/sessions/${SES}/transcribe`)).toEqual([]);
  });

  it("asks for an explicitly installed model and never downloads one", async () => {
    host.route("GET /v1/transcription/models", () => models({ installed: [] }));
    panel();
    expect(await screen.findByText(/No speech model is installed/)).toBeTruthy();
    expect(screen.getByText(/never downloads models on its own/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Transcribe/ })).toBeNull();
  });

  it("starts a transcription with the chosen model and language", async () => {
    const user = userEvent.setup();
    panel();
    const start = await screen.findByRole("button", { name: "Transcribe speech" });
    await user.selectOptions(screen.getByRole("combobox", { name: /Language/ }), "en");
    await user.click(start);
    expect(host.posts(`/v1/sessions/${SES}/transcribe`)).toEqual([
      { model: "base.en", language: "en", force: false },
    ]);
    expect(await screen.findByText(/Transcribing/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Transcribe speech" })).toHaveProperty(
      "disabled",
      true,
    );
  });

  it("lists timed lines that seek the player, and rebuilds on request", async () => {
    segments = [line(1, 0, "Meet me at the bridge."), line(2, 62_000, "Go, go!", 0.3)];
    const user = userEvent.setup();
    const onSeek = panel();
    const list = await screen.findByRole("list", { name: "2 transcript lines" });
    expect(within(list).getByText("Meet me at the bridge.")).toBeTruthy();
    expect(within(list).getAllByText("Low confidence")).toHaveLength(1);
    await user.click(within(list).getByRole("button", { name: "Play from 1:02" }));
    expect(onSeek).toHaveBeenCalledWith(62_000);
    await user.click(screen.getByRole("button", { name: "Rebuild transcript" }));
    expect(host.posts(`/v1/sessions/${SES}/transcribe`)).toEqual([
      { model: "base.en", language: "auto", force: true },
    ]);
  });

  it("deletes the transcript only after confirmation", async () => {
    segments = [line(1, 0, "Meet me at the bridge.")];
    const user = userEvent.setup();
    panel();
    await user.click(await screen.findByRole("button", { name: "Delete transcript…" }));
    expect(screen.getByText(/Your video files are not affected/)).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Keep it" }));
    expect(host.calls.filter((c) => c.method === "DELETE")).toEqual([]);
    await user.click(screen.getByRole("button", { name: "Delete transcript…" }));
    await user.click(screen.getByRole("button", { name: "Delete transcript" }));
    expect(host.calls.filter((c) => c.method === "DELETE")).toHaveLength(1);
    expect(await screen.findByText("This session has no transcript yet.")).toBeTruthy();
  });

  it("refreshes when a transcription finishes and shows a failure", async () => {
    panel();
    await screen.findByRole("button", { name: "Transcribe speech" });
    const running = job({
      kind: "transcribe",
      state: "transcribing",
      params: { session_id: SES, model: "base.en" },
      progress: { done: 50, total: 200 },
    });
    upsertJob(running);
    expect(await screen.findByText("Transcribing (25%)… ", { exact: false })).toBeTruthy();
    segments = [line(1, 0, "Meet me at the bridge.")];
    upsertJob({
      ...running,
      state: "failed",
      error: {
        code: "transcription.partial_failure",
        message: "Some clips could not be transcribed; completed clips are kept.",
        retryable: true,
      },
    });
    expect(await screen.findByText("Meet me at the bridge.")).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toContain("completed clips are kept");
  });

  it("explains a refused request", async () => {
    host.route(`POST /v1/sessions/${SES}/transcribe`, () => {
      throw {
        code: "job.invalid_params",
        message: "That speech model is not installed.",
        retryable: false,
      };
    });
    const user = userEvent.setup();
    panel();
    await user.click(await screen.findByRole("button", { name: "Transcribe speech" }));
    expect((await screen.findByRole("alert")).textContent).toContain("not installed");
  });
});
