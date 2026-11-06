// SPDX-License-Identifier: AGPL-3.0-or-later
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WatchedFolders } from "./WatchedFolders";
import { XboxOnboarding, XBOX_SUPPORT_URL } from "./XboxOnboarding";
import { describeFolder, parsePatterns, type WatchedFolderView } from "./watched";

const invoke = vi.hoisted(() => vi.fn());
const open = vi.hoisted(() => vi.fn());
vi.mock("@tauri-apps/api/core", () => ({ invoke }));
vi.mock("@tauri-apps/plugin-dialog", () => ({ open }));

function folder(overrides: Record<string, unknown> = {}) {
  return {
    schema_version: "1.5",
    id: 1,
    path: "C:\\Users\\player\\OneDrive\\Videos\\Xbox Game DVR",
    source_kind: "xbox",
    mode: "reference",
    recursive: true,
    include: [],
    exclude: [".*", "**/.*/**"],
    enabled: true,
    created_at: "2026-11-20T05:40:10Z",
    updated_at: "2026-11-20T05:40:10Z",
    availability: "available",
    stats: { tracked: 4, imported: 3, in_progress: 0, failed: 1 },
    ...overrides,
  };
}

const watching = {
  id: 1,
  state: "watching",
  pending: 2,
  cloud_only: 1,
  reported: 3,
  rejected: 0,
  next_check_ms: null,
};

function mockList(folders: unknown[], status: unknown[] = []) {
  invoke.mockImplementation((cmd: string) => {
    if (cmd === "watched_folders_list") return Promise.resolve({ folders, status });
    if (cmd === "watched_folder_files") {
      return Promise.resolve([
        {
          relative_path: "Halo/broken.mp4",
          size_bytes: 10,
          mtime_ns: 1,
          state: "failed",
          attempts: 1,
          error: { code: "media.damaged", message: "The file is damaged.", retryable: false },
          updated_at: "2026-11-20T05:40:12Z",
        },
      ]);
    }
    return Promise.resolve(folder());
  });
}

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  cleanup();
  invoke.mockReset();
  open.mockReset();
});

describe("WatchedFolders", () => {
  it("shows loading, then the empty state", async () => {
    mockList([]);
    render(<WatchedFolders />);
    expect(screen.getByText("Loading watched folders…")).toBeTruthy();
    expect(await screen.findByText(/No folders yet/)).toBeTruthy();
  });

  it("shows an error when the worker cannot be reached", async () => {
    invoke.mockRejectedValue({ code: "worker.unavailable", message: "not running" });
    render(<WatchedFolders />);
    expect((await screen.findByRole("alert")).textContent).toContain("not running");
  });

  it("lists folders with live status", async () => {
    mockList([folder()], [watching]);
    render(<WatchedFolders />);
    const status = await screen.findByTestId("folder-1-status");
    expect(status.textContent).toBe(
      "Watching · 3 imported · 2 waiting for files to finish copying · 1 still in the cloud · 1 failed",
    );
    expect(screen.getByText(folder().path as string)).toBeTruthy();
  });

  it("adds a folder chosen in the picker with the selected source", async () => {
    mockList([]);
    open.mockResolvedValue("/Users/me/OBS");
    render(<WatchedFolders />);
    await screen.findByText(/No folders yet/);
    fireEvent.change(screen.getByLabelText("Source"), { target: { value: "obs" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Add folder…" }));
    });
    expect(invoke).toHaveBeenCalledWith("watched_folder_add", {
      path: "/Users/me/OBS",
      sourceKind: "obs",
    });
    expect(screen.getByRole("status").textContent).toMatch(/Folder added/);
  });

  it("does nothing when the picker is cancelled", async () => {
    mockList([]);
    open.mockResolvedValue(null);
    render(<WatchedFolders />);
    await screen.findByText(/No folders yet/);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Add folder…" }));
    });
    expect(invoke).not.toHaveBeenCalledWith("watched_folder_add", expect.anything());
  });

  it("pauses, filters, shows failures, and stops watching without touching files", async () => {
    mockList([folder()], [watching]);
    render(<WatchedFolders />);
    const item = (await screen.findByText(folder().path as string)).closest("li");
    if (item === null) throw new Error("folder item not found");
    const scope = within(item);

    await act(async () => {
      fireEvent.click(scope.getByLabelText("Watch this folder"));
    });
    expect(invoke).toHaveBeenCalledWith("watched_folder_update", {
      id: 1,
      changes: { enabled: false },
    });

    fireEvent.change(scope.getByLabelText(/Only import files matching/), {
      target: { value: "Halo/**, *.mkv" },
    });
    await act(async () => {
      fireEvent.click(scope.getByRole("button", { name: "Save filters" }));
    });
    expect(invoke).toHaveBeenCalledWith("watched_folder_update", {
      id: 1,
      changes: { include: ["Halo/**", "*.mkv"], exclude: [".*", "**/.*/**"] },
    });

    await act(async () => {
      fireEvent.click(scope.getByRole("button", { name: "Show failed files" }));
    });
    expect(scope.getByLabelText("Failed files").textContent).toContain(
      "Halo/broken.mp4: The file is damaged.",
    );

    await act(async () => {
      fireEvent.click(scope.getByRole("button", { name: "Stop watching" }));
    });
    expect(invoke).toHaveBeenCalledWith("watched_folder_remove", { id: 1 });
    expect(screen.getByRole("status").textContent).toMatch(/files were not changed/);
  });

  it("reports a failed action", async () => {
    mockList([folder()], [watching]);
    render(<WatchedFolders />);
    await screen.findByTestId("folder-1-status");
    invoke.mockImplementation((cmd: string) =>
      cmd === "watched_folder_remove"
        ? Promise.reject({ code: "watch.folder_not_found", message: "gone" })
        : Promise.resolve({ folders: [folder()], status: [watching] }),
    );
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Stop watching" }));
    });
    expect(screen.getByRole("status").textContent).toBe("Could not complete that: gone");
  });
});

describe("describeFolder", () => {
  const view = (f: Record<string, unknown>, status?: unknown) =>
    ({ folder: folder(f), status }) as unknown as WatchedFolderView;

  it("explains paused and unavailable folders", () => {
    expect(describeFolder(view({ enabled: false }))).toBe("Paused — not watched");
    expect(
      describeFolder(view({}, { ...watching, state: "unavailable", next_check_ms: 14_200 })),
    ).toBe("Unavailable — the folder cannot be read right now. Checking again in 15 s.");
    expect(
      describeFolder(view({ stats: { tracked: 0, imported: 0, in_progress: 0, failed: 0 } })),
    ).toBe("Starting… · 0 imported");
  });

  it("parses comma and newline separated patterns", () => {
    expect(parsePatterns(" Halo/** ,\n*.mkv,, ")).toEqual(["Halo/**", "*.mkv"]);
  });
});

describe("XboxOnboarding", () => {
  it("explains the OneDrive path without claiming Xbox access", () => {
    render(<XboxOnboarding onAdded={() => undefined} />);
    const card = screen.getByRole("region", { name: /Import Xbox captures/ });
    expect(card.textContent).toContain("does not connect to Xbox or OneDrive");
    expect(card.textContent).toContain(XBOX_SUPPORT_URL);
    expect(card.textContent).toContain("Always keep on this device");
  });

  it("adds the chosen folder as an Xbox source and hides itself", async () => {
    const onAdded = vi.fn();
    invoke.mockResolvedValue(folder());
    open.mockResolvedValue("C:\\OneDrive\\Xbox Game DVR");
    render(<XboxOnboarding onAdded={onAdded} />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Choose captures folder…" }));
    });
    expect(invoke).toHaveBeenCalledWith("watched_folder_add", {
      path: "C:\\OneDrive\\Xbox Game DVR",
      sourceKind: "xbox",
    });
    expect(onAdded).toHaveBeenCalled();
    expect(screen.queryByRole("region", { name: /Import Xbox captures/ })).toBeNull();
  });

  it("can be skipped and stays skipped", () => {
    const { unmount } = render(<XboxOnboarding onAdded={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: "Not now" }));
    expect(screen.queryByRole("region", { name: /Import Xbox captures/ })).toBeNull();
    unmount();
    render(<XboxOnboarding onAdded={() => undefined} />);
    expect(screen.queryByRole("region", { name: /Import Xbox captures/ })).toBeNull();
  });

  it("shows why a folder could not be added", async () => {
    invoke.mockRejectedValue({ code: "watch.already_watched", message: "already watched" });
    open.mockResolvedValue("/x");
    render(<XboxOnboarding onAdded={() => undefined} />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Choose captures folder…" }));
    });
    expect(screen.getByRole("alert").textContent).toContain("already watched");
  });
});
