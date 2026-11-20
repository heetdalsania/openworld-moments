// SPDX-License-Identifier: AGPL-3.0-or-later
import { invoke } from "@tauri-apps/api/core";
import { useEffect, useState } from "react";
import { describeError } from "./api";
import { useAction } from "./query";

interface Location {
  supported: boolean;
  path?: string | null;
  available?: boolean;
}

/** Native selection recovers an existing, relocated library. Switching takes
 * effect on relaunch; the app never moves an open database or source footage. */
export function LibraryLocation() {
  const [location, setLocation] = useState<Location | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    void invoke<Location>("library_location")
      .then((info) => {
        if (!cancelled) setLocation(info);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);
  const choose = useAction(async () => {
    setNotice(null);
    const result = await invoke<{ selected: boolean; restart_required?: boolean }>(
      "library_select",
    );
    if (result.selected)
      setNotice(
        result.restart_required
          ? "Library selected. Quit and reopen OpenWorld Moments to use it. Your current library was kept."
          : "Library access checked. Its records and queued jobs were kept.",
      );
  });
  if (!location?.supported) return null;
  return (
    <section className="panel" aria-labelledby="library-location-heading">
      <h2 id="library-location-heading">Library location</h2>
      {location.path && <p className="path">{location.path}</p>}
      {!location.available && (
        <p role="status">
          The library is unavailable. Reconnect its drive or select it again. Its records are kept.
        </p>
      )}
      <p>
        To move your library, quit the app first, move the entire library folder in Finder, then
        reopen the app and select that folder here. Only select libraries you trust. The app never
        moves an open library or your original clips.
      </p>
      <button type="button" disabled={choose.busy} onClick={() => void choose.run()}>
        Choose existing library…
      </button>
      {notice && <p role="status">{notice}</p>}
      {choose.error && <p role="alert">{describeError(choose.error)}</p>}
    </section>
  );
}
