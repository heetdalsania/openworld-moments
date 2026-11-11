// SPDX-License-Identifier: AGPL-3.0-or-later
import { useId } from "react";
import { setPrivacy, usePreferences } from "./preferences";

/**
 * M31 informed opt-in for the two features that use a network: the phone upload page on
 * the local network and optional model downloads. Both start off; each choice says what
 * happens before it can be turned on, and can be turned off again at any time.
 * `embedded`: inside setup, whose step heading already names it.
 */
export function PrivacyChoices({ embedded = false }: { embedded?: boolean }) {
  const prefs = usePreferences();
  const phoneHelp = useId();
  const modelHelp = useId();
  const body = (
    <>
      <p>
        OpenWorld Moments works on this computer only. There is no account, no telemetry and no
        cloud upload. Two optional features use a network, and both stay off until you turn them on
        here.
      </p>
      <fieldset>
        <legend>Optional network features</legend>
        <div className="privacy-choice">
          <label className="check">
            <input
              type="checkbox"
              checked={prefs.privacy.phoneLan}
              aria-describedby={phoneHelp}
              onChange={(e) => setPrivacy("phoneLan", e.target.checked)}
            />
            Allow phone transfer on my home network
          </label>
          <p id={phoneHelp} className="muted">
            When you open <em>Import from phone</em>, a temporary upload page starts on your local
            network so your phone can send clips (for example from the PlayStation App). It uses a
            secret link over plain HTTP, not encryption: anyone on the same network who gets the
            link can send files until the page closes after 10 minutes or when you leave that
            screen. Use it only on a network you trust. Nothing is sent to the internet.
          </p>
        </div>
        <div className="privacy-choice">
          <label className="check">
            <input
              type="checkbox"
              checked={prefs.privacy.modelDownloads}
              aria-describedby={modelHelp}
              onChange={(e) => setPrivacy("modelDownloads", e.target.checked)}
            />
            Allow optional speech-model downloads
          </label>
          <p id={modelHelp} className="muted">
            Lets you install speech-to-text models (about 75–150 MiB each) from the sources listed
            in the app&apos;s signed catalog. Each download starts only when you choose{" "}
            <em>Install</em>, and is checked against its published checksum. Audio, transcripts and
            footage are never uploaded. Editing works without any model.
          </p>
        </div>
      </fieldset>
      <p className="muted" role="status">
        Phone transfer is {prefs.privacy.phoneLan ? "allowed" : "off"}. Model downloads are{" "}
        {prefs.privacy.modelDownloads ? "allowed" : "off"}.
      </p>
    </>
  );
  if (embedded) return <div className="panel privacy-choices">{body}</div>;
  return (
    <section className="panel privacy-choices" aria-labelledby={`${phoneHelp}-heading`}>
      <h2 id={`${phoneHelp}-heading`}>Privacy choices</h2>
      {body}
    </section>
  );
}
