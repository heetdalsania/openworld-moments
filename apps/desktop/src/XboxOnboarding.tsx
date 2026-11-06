// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from "react";
import { addWatched, errorMessage, pickFolder } from "./watched";

export const XBOX_SUPPORT_URL =
  "https://support.xbox.com/en-US/help/games-apps/my-games-apps/back-up-game-clips";
const DISMISSED_KEY = "owm.onboarding.xbox.dismissed";

function readDismissed(): boolean {
  try {
    return window.localStorage.getItem(DISMISSED_KEY) === "1";
  } catch {
    return false;
  }
}

function saveDismissed(): void {
  try {
    window.localStorage.setItem(DISMISSED_KEY, "1");
  } catch {
    // Storage can be unavailable; the card simply shows again next time.
  }
}

/**
 * Optional onboarding step (spec 6.1, 10.2): point the app at the folder where
 * OneDrive syncs Xbox captures. The app only reads that folder; it does not
 * connect to Xbox or OneDrive.
 */
export function XboxOnboarding({ onAdded }: { onAdded: () => void }) {
  const [dismissed, setDismissed] = useState(readDismissed);
  const [message, setMessage] = useState<string | null>(null);
  if (dismissed) return null;

  async function choose() {
    setMessage(null);
    const path = await pickFolder("Choose the OneDrive folder with your Xbox captures");
    if (path === null) return;
    try {
      await addWatched(path, "xbox");
      saveDismissed();
      setDismissed(true);
      onAdded();
    } catch (error) {
      setMessage(`That folder could not be added: ${errorMessage(error)}`);
    }
  }

  return (
    <section aria-labelledby="xbox-heading" className="panel onboarding">
      <h2 id="xbox-heading">Import Xbox captures automatically (optional)</h2>
      <p>
        OpenWorld Moments does not connect to Xbox or OneDrive. It watches a folder on this computer
        that OneDrive keeps in sync:
      </p>
      <ol>
        <li>
          On your Xbox, back up or upload your captures to OneDrive. Xbox Support explains how:{" "}
          <span className="url">{XBOX_SUPPORT_URL}</span>
        </li>
        <li>Install OneDrive on this computer and sign in with the same Microsoft account.</li>
        <li>
          In OneDrive, find the folder where the captures arrive and choose{" "}
          <em>Always keep on this device</em>, so the videos are downloaded, not just listed.
        </li>
        <li>Choose that folder below.</li>
      </ol>
      <p className="muted">
        Clips appear here after OneDrive finishes downloading them. Files are never moved or
        deleted.
      </p>
      <div className="row">
        <button type="button" onClick={() => void choose()}>
          Choose captures folder…
        </button>
        <button
          type="button"
          onClick={() => {
            saveDismissed();
            setDismissed(true);
          }}
        >
          Not now
        </button>
      </div>
      {message && <p role="alert">{message}</p>}
    </section>
  );
}
