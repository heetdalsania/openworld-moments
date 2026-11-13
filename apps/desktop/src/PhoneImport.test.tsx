// SPDX-License-Identifier: AGPL-3.0-or-later
import { act, cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { PhoneStatus } from "./phone";
import { PhoneImport } from "./PhoneImport";

const invoke = vi.hoisted(() => vi.fn());
const listen = vi.hoisted(() => vi.fn());
vi.mock("@tauri-apps/api/core", () => ({ invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen }));

type Listener = (event: { payload: unknown }) => void;
let phoneListener: Listener | undefined;
let interfaces: { name: string; address: string }[];
let status: PhoneStatus;
const calls: { command: string; args: unknown }[] = [];

const ACTIVE: PhoneStatus = {
  state: "active",
  address: "192.168.1.20",
  port: 52011,
  url: `http://192.168.1.20:52011/u/${"f".repeat(64)}/`,
  qr_svg: '<svg xmlns="http://www.w3.org/2000/svg"></svg>',
  expires_in_s: 600,
  uploads: [],
};

beforeEach(() => {
  interfaces = [
    { name: "en0", address: "192.168.1.20" },
    { name: "en7", address: "10.0.0.4" },
  ];
  status = { state: "idle", uploads: [] };
  calls.length = 0;
  invoke.mockImplementation((command: string, args?: unknown) => {
    calls.push({ command, args });
    if (command === "phone_interfaces") return Promise.resolve(interfaces);
    if (command === "phone_status") return Promise.resolve(status);
    if (command === "phone_start") return Promise.resolve(ACTIVE);
    if (command === "phone_stop") {
      return Promise.resolve({ state: "ended", uploads: [], ended_reason: "closed_by_desktop" });
    }
    return Promise.reject(new Error(command));
  });
  listen.mockImplementation((_name: string, cb: Listener) => {
    phoneListener = cb;
    return Promise.resolve(() => undefined);
  });
});

afterEach(() => {
  cleanup();
  invoke.mockReset();
  listen.mockReset();
  vi.useRealTimers();
});

describe("import from phone", () => {
  it("explains the security limits before anything starts", async () => {
    render(<PhoneImport />);
    const note = screen.getByRole("note");
    expect(note.textContent).toMatch(/network you trust/);
    expect(note.textContent).toMatch(/plain HTTP/);
    expect(note.textContent).toMatch(/Never use it on public or hotel Wi-Fi/);
    expect(note.textContent).toMatch(/after 10 minutes/);
    expect(await screen.findByRole("combobox", { name: "Network connection" })).toBeTruthy();
    expect(screen.queryByRole("img", { name: /QR code/ })).toBeNull(); // nothing is open yet
  });

  it("lists only private connections and starts on the chosen one", async () => {
    const user = userEvent.setup();
    render(<PhoneImport />);
    const select = await screen.findByRole("combobox", { name: "Network connection" });
    expect(
      within(select)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["en0 (192.168.1.20)", "en7 (10.0.0.4)"]);
    await user.selectOptions(select, "10.0.0.4");
    await user.click(screen.getByRole("button", { name: "Show QR code" }));
    expect(calls.find((c) => c.command === "phone_start")?.args).toEqual({
      address: "10.0.0.4",
      port: null,
    });
    const qr = await screen.findByRole("img", { name: /QR code/ });
    expect(qr.getAttribute("src")).toMatch(/^data:image\/svg\+xml/);
    expect(screen.getByText(ACTIVE.url ?? "")).toBeTruthy();
    expect(screen.getByRole("timer").textContent).toBe("Closes in 10:00");
  });

  it("counts down and follows uploads from the phone", async () => {
    // Only the countdown interval is faked, so it ticks exactly when the test says.
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    status = ACTIVE;
    // Flush the async host status and countdown effect before advancing its interval.
    await act(async () => {
      render(<PhoneImport />);
    });
    expect(screen.getByRole("timer")).toBeTruthy();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(screen.getByRole("timer").textContent).toBe("Closes in 9:57");
    act(() =>
      phoneListener?.({
        payload: {
          ...ACTIVE,
          uploads: [
            { seq: 1, name: "Heist.mp4", size: 100, received: 40, status: "receiving" },
            {
              seq: 2,
              name: "notes.pdf",
              size: 5,
              received: 0,
              status: "rejected",
              reason: "unsupported_type",
            },
            {
              seq: 3,
              name: "Chase.mp4",
              size: 9,
              received: 9,
              status: "imported",
              asset_id: "ast_01JCBQ00000000000000000001",
            },
            { seq: 4, name: "Chase again.mp4", size: 9, received: 9, status: "duplicate" },
            {
              seq: 5,
              name: "Broken.mp4",
              size: 9,
              received: 9,
              status: "import_failed",
              reason: "media.damaged",
            },
            { seq: 6, name: "Dropped.mp4", size: 9, received: 3, status: "interrupted" },
          ],
        },
      }),
    );
    const list = screen.getByRole("list");
    const text = list.textContent ?? "";
    expect(text).toContain("Receiving 40%");
    expect(text).toContain("Refused: Not a supported video type");
    expect(text).toContain("Added to the library");
    expect(text).toContain("Already in the library");
    expect(text).toContain("Not added: Damaged or incomplete video");
    expect(text).toContain("Interrupted, nothing was kept");
    expect(within(list).getByRole("link", { name: "Open" }).getAttribute("href")).toBe(
      "#/asset/ast_01JCBQ00000000000000000001",
    );
  });

  it("closes the page on request and when leaving the screen", async () => {
    status = ACTIVE;
    const user = userEvent.setup();
    const view = render(<PhoneImport />);
    await user.click(await screen.findByRole("button", { name: "Close upload page" }));
    expect(await screen.findByText("You closed the upload link.")).toBeTruthy();
    const before = calls.filter((c) => c.command === "phone_stop").length;
    view.unmount();
    expect(calls.filter((c) => c.command === "phone_stop").length).toBe(before + 1);
  });

  it("explains when there is no private network", async () => {
    interfaces = [];
    render(<PhoneImport />);
    expect((await screen.findByRole("alert")).textContent).toMatch(
      /not connected to a private network/,
    );
    expect(screen.queryByRole("button", { name: "Show QR code" })).toBeNull();
  });

  it("shows why a session could not start", async () => {
    invoke.mockImplementation((command: string) => {
      if (command === "phone_interfaces") return Promise.resolve(interfaces);
      if (command === "phone_status") return Promise.resolve({ state: "idle", uploads: [] });
      if (command === "phone_start") {
        return Promise.reject({
          code: "phone.address_not_allowed",
          message: "Choose one of this computer's private network addresses.",
          retryable: false,
        });
      }
      return Promise.resolve({ state: "ended", uploads: [] });
    });
    const user = userEvent.setup();
    render(<PhoneImport />);
    await user.click(await screen.findByRole("button", { name: "Show QR code" }));
    expect((await screen.findByRole("alert")).textContent).toMatch(/private network addresses/);
  });
});

it("explains Mac firewall and local-network access before a session starts", async () => {
  render(<PhoneImport />);
  await screen.findByRole("combobox", { name: "Network connection" });
  const guide = screen.getByRole("region", { name: "Mac network permissions" });
  expect(guide.textContent).toContain("Keep the firewall on");
  expect(guide.textContent).toContain("Local Network in System Settings");
  expect(guide.textContent).toContain("waking the Mac never reopens phone transfer automatically");
  expect(calls.some((c) => c.command === "phone_start")).toBe(false);
});
