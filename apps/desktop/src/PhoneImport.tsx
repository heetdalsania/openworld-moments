// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useId, useState } from "react";
import { describeError } from "./api";
import {
  describeEnd,
  describeUpload,
  type NetInterface,
  onPhoneStatus,
  type PhoneStatus,
  phoneInterfaces,
  phoneStatus,
  startPhone,
  stopPhone,
} from "./phone";
import { setPrivacy, usePreferences } from "./preferences";
import { useAction } from "./query";
import { routeHref } from "./route";

function formatCountdown(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

/** Counts down locally from the last status the host reported. */
function useCountdown(status: PhoneStatus | null): number | null {
  const [left, setLeft] = useState<{ base: number | undefined; value: number } | null>(null);
  const base = status?.state === "active" ? status.expires_in_s : undefined;
  const current = left && left.base === base ? left.value : (base ?? null);
  useEffect(() => {
    if (base === undefined) return;
    const timer = window.setInterval(() => {
      setLeft((previous) => {
        const start = previous && previous.base === base ? previous.value : base;
        return { base, value: Math.max(0, start - 1) };
      });
    }, 1000);
    return () => window.clearInterval(timer);
  }, [base]);
  return current;
}

/**
 * "Import from phone": a temporary upload page on this computer's private network
 * (spec 6.2, 9.2.2). It exists only while this screen is open.
 */
export function PhoneImport() {
  const [interfaces, setInterfaces] = useState<NetInterface[] | null>(null);
  const [address, setAddress] = useState("");
  const [status, setStatus] = useState<PhoneStatus | null>(null);
  const start = useAction(async () => setStatus(await startPhone(address)));
  const stop = useAction(async () => setStatus(await stopPhone()));
  const left = useCountdown(status);
  const selectId = useId();

  useEffect(() => {
    let cancelled = false;
    phoneInterfaces()
      .then((found) => {
        if (cancelled) return;
        setInterfaces(found);
        setAddress((current) => current || found[0]?.address || "");
      })
      .catch(() => {
        if (!cancelled) setInterfaces([]);
      });
    phoneStatus()
      .then((current) => {
        if (!cancelled) setStatus(current);
      })
      .catch(() => undefined);
    const unlisten = onPhoneStatus((next) => {
      if (!cancelled) setStatus(next);
    });
    return () => {
      cancelled = true;
      void unlisten.then((off) => off());
      // Leaving the screen closes the upload page immediately.
      void stopPhone().catch(() => undefined);
    };
  }, []);

  const allowed = usePreferences().privacy.phoneLan;
  const active = status?.state === "active";
  const uploads = status?.uploads ?? [];

  return (
    <section className="view phone" aria-labelledby="phone-heading">
      <h1 id="phone-heading">Import from phone</h1>
      <p>
        Send clips from your phone (for example ones downloaded from the PlayStation App) straight
        to this computer over your Wi-Fi. No account or cloud service is involved.
      </p>
      <div className="notice-box warn" role="note">
        <strong>Use this only on a network you trust, like your home Wi-Fi.</strong> The upload page
        uses plain HTTP protected by a secret link, not encryption. Anyone on the same network who
        gets the link can send files until the session ends. Never use it on public or hotel Wi-Fi.
        The page closes when you leave this screen, after 10 minutes, or when you tap "I'm done" on
        the phone.
      </div>

      {!active && (
        <div className="notice-box" role="region" aria-label="Mac network permissions">
          <strong>On a Mac, check network permissions before showing the code.</strong>
          <p>
            If macOS asks, allow OpenWorld Moments to use your local network and receive incoming
            connections. You can review Local Network in System Settings → Privacy &amp; Security,
            and Firewall in Network → Firewall → Options. Keep the firewall on; allow this app only
            on a trusted network. A denied request leaves your library unchanged.
          </p>
          <p>
            If the phone cannot connect, close this page, check those permissions and that both
            devices use the same Wi-Fi, then show a new code. The code also closes when this Mac
            sleeps; waking the Mac never reopens phone transfer automatically.
          </p>
        </div>
      )}

      {!active && !allowed && (
        <div className="panel phone-consent">
          <h2>Phone transfer is off</h2>
          <p>
            Allowing it lets this screen open the temporary upload page described above when you
            choose Show QR code. You can turn it off again in Settings → Privacy choices.
          </p>
          <button type="button" className="primary" onClick={() => setPrivacy("phoneLan", true)}>
            Allow phone transfer on this network
          </button>
        </div>
      )}
      {!active && allowed && (
        <div className="phone-setup">
          {interfaces === null && <p role="status">Looking for network connections…</p>}
          {interfaces?.length === 0 && (
            <p role="alert">
              This computer is not connected to a private network. Connect to your home Wi-Fi or
              Ethernet and come back.
            </p>
          )}
          {interfaces && interfaces.length > 0 && (
            <>
              <label htmlFor={selectId}>Network connection</label>
              <select
                id={selectId}
                value={address}
                onChange={(event) => setAddress(event.target.value)}
              >
                {interfaces.map((iface) => (
                  <option key={`${iface.name}-${iface.address}`} value={iface.address}>
                    {iface.name} ({iface.address})
                  </option>
                ))}
              </select>
              <p className="muted">Your phone must be on this same network.</p>
              <div className="row">
                <button
                  type="button"
                  className="primary"
                  disabled={!address || start.busy || status?.state === "starting"}
                  onClick={() => void start.run()}
                >
                  {start.busy ? "Opening…" : "Show QR code"}
                </button>
              </div>
            </>
          )}
          {start.error && <p role="alert">{describeError(start.error)}</p>}
          {status?.state === "ended" && (
            <p role="status">
              {status.error
                ? describeError({ ...status.error, retryable: false })
                : describeEnd(status.ended_reason)}
            </p>
          )}
        </div>
      )}

      {active && status.url && (
        <div className="phone-active">
          {status.qr_svg && (
            <img
              className="qr"
              src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(status.qr_svg)}`}
              alt="QR code that opens the upload page on your phone"
              width={240}
              height={240}
            />
          )}
          <div>
            <p>Scan the code with your phone&apos;s camera, then choose the videos to send.</p>
            <p className="muted">
              Or open this address on the phone: <code className="url">{status.url}</code>
            </p>
            {left !== null && (
              <p role="timer" aria-live="off">
                Closes in {formatCountdown(left)}
              </p>
            )}
            <button type="button" disabled={stop.busy} onClick={() => void stop.run()}>
              Close upload page
            </button>
          </div>
        </div>
      )}

      {uploads.length > 0 && (
        <section aria-labelledby="phone-uploads">
          <h2 id="phone-uploads">From your phone</h2>
          <ul className="phone-uploads" aria-live="polite">
            {uploads.map((upload) => (
              <li key={upload.seq}>
                <span className="file">{upload.name}</span>
                <span className={`status status-${upload.status}`}>{describeUpload(upload)}</span>
                {upload.asset_id && (
                  <a href={routeHref({ view: "asset", id: upload.asset_id })}>Open</a>
                )}
              </li>
            ))}
          </ul>
          <p className="muted">
            Received files are copied into the library. Files that are not video are never added.
          </p>
        </section>
      )}
    </section>
  );
}
