// SPDX-License-Identifier: AGPL-3.0-or-later
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";

const invoke = vi.hoisted(() => vi.fn());
vi.mock("@tauri-apps/api/core", () => ({ invoke }));

afterEach(() => {
  cleanup();
  invoke.mockReset();
});

describe("App placeholder", () => {
  it("shows the planning-stage placeholder and host version", async () => {
    invoke.mockResolvedValue({ name: "OpenWorld Moments", version: "0.0.0", stage: "planning" });
    render(<App />);

    expect(screen.getByRole("heading", { name: "OpenWorld Moments" })).toBeTruthy();
    expect(screen.getByText(/Planning stage/)).toBeTruthy();
    expect(await screen.findByText("Desktop host 0.0.0 (planning)")).toBeTruthy();
    expect(invoke).toHaveBeenCalledWith("app_info");
  });

  it("reports when the desktop host is unavailable", async () => {
    invoke.mockRejectedValue(new Error("no host"));
    render(<App />);

    expect(await screen.findByText(/Desktop host unavailable/)).toBeTruthy();
  });
});
