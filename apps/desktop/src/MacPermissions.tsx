// SPDX-License-Identifier: AGPL-3.0-or-later
import { useId, useState } from "react";
import { type ApiError, describeError } from "./api";
import { openGuide, openSystemSettings, type SettingsPane } from "./menu";

/**
 * M38: what macOS may ask, and how to recover when access was refused. Every fix is to
 * allow OpenWorld Moments in a specific place; none turns a system protection off, and
 * the app never needs Full Disk Access.
 */
export function MacPermissions() {
  const id = useId();
  const [error, setError] = useState<string | null>(null);
  const open = (pane: SettingsPane) => {
    setError(null);
    openSystemSettings(pane).catch((e: ApiError) => setError(describeError(e)));
  };
  return (
    <section className="panel mac-permissions" aria-labelledby={`${id}-heading`}>
      <h2 id={`${id}-heading`}>macOS permissions</h2>
      <p>
        macOS asks before an app reads some places or uses your network. OpenWorld Moments only asks
        when you use a feature that needs it, and never needs Full Disk Access.
      </p>
      <dl className="permission-list">
        <dt>Folders and drives</dt>
        <dd>
          When you choose files in Desktop, Documents, Downloads, an external drive or a network
          volume, macOS may ask “OpenWorld Moments would like to access files in…”. Choose{" "}
          <strong>Allow</strong>. If you chose Don’t Allow, turn OpenWorld Moments on under{" "}
          <em>Privacy &amp; Security → Files and Folders</em>, then choose the folder again in the
          app.
          <div className="row">
            <button type="button" onClick={() => open("files-and-folders")}>
              Open Files and Folders settings
            </button>
          </div>
        </dd>
        <dt>Phone transfer</dt>
        <dd>
          The first time you open the phone upload page, macOS asks to let OpenWorld Moments find
          devices on your local network: choose <strong>Allow</strong>. If the macOS firewall is on,
          it may also ask to accept incoming connections: choose <strong>Allow</strong> and keep the
          firewall on. If you refused, turn OpenWorld Moments on under{" "}
          <em>Privacy &amp; Security → Local Network</em>.
          <div className="row">
            <button type="button" onClick={() => open("local-network")}>
              Open Local Network settings
            </button>
          </div>
        </dd>
        <dt>External drives</dt>
        <dd>
          Clips kept on a drive (imported by reference) show as unavailable while it is
          disconnected. Nothing is deleted: reconnect the drive and they come back.
        </dd>
        <dt>OneDrive and iCloud Drive</dt>
        <dd>
          Files kept only in the cloud show <em>Download required</em>. In Finder, choose{" "}
          <em>Download Now</em> or <em>Always Keep on This Device</em> for your captures folder,
          then import again.
        </dd>
      </dl>
      <div className="row">
        <button
          type="button"
          onClick={() => {
            setError(null);
            openGuide("macos-permissions").catch((e: ApiError) => setError(describeError(e)));
          }}
        >
          Open the macOS guide
        </button>
      </div>
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
