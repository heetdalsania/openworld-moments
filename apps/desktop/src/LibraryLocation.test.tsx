// SPDX-License-Identifier: AGPL-3.0-or-later
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { LibraryLocation } from "./LibraryLocation";
const invoke = vi.hoisted(() => vi.fn());
vi.mock("@tauri-apps/api/core", () => ({ invoke }));
afterEach(() => {
  cleanup();
  invoke.mockReset();
});

it.each([true, false])(
  "selects a moved library only through the host, picker selected %s",
  async (selected) => {
    invoke.mockImplementation((command: string) =>
      Promise.resolve(
        command === "library_location"
          ? { supported: true, path: "/Volumes/Captures ✓/library", available: true }
          : { selected, restart_required: true },
      ),
    );
    render(<LibraryLocation />);
    const button = await screen.findByRole("button", { name: "Choose existing library…" });
    expect(screen.getByText(/quit the app first/)).toBeTruthy();
    await act(async () => {
      fireEvent.click(button);
    });
    expect(invoke).toHaveBeenCalledWith("library_select");
    expect(screen.queryByRole("status")?.textContent ?? "").toBe(
      selected
        ? "Library selected. Quit and reopen OpenWorld Moments to use it. Your current library was kept."
        : "",
    );
  },
);

it("keeps an offline library recoverable when selection fails", async () => {
  invoke.mockImplementation((command: string) =>
    command === "library_location"
      ? Promise.resolve({ supported: true, path: "/Volumes/Offline/library", available: false })
      : Promise.reject({ message: "Download the library before selecting it.", retryable: true }),
  );
  render(<LibraryLocation />);
  const button = await screen.findByRole("button", { name: "Choose existing library…" });
  expect(screen.getByRole("status").textContent).toContain("Its records are kept");
  await act(async () => {
    fireEvent.click(button);
  });
  expect(screen.getByRole("alert").textContent).toContain("Download the library");
});
