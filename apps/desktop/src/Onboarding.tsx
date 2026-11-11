// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useId, useRef, useState } from "react";
import { AppearanceSettings } from "./AppearanceSettings";
import type { ImportMode } from "./api";
import { saveMode, savedMode } from "./ImportPanel";
import { setOnboarding } from "./preferences";
import { PrivacyChoices } from "./PrivacyChoices";
import { SystemPanel } from "./SystemPanel";
import { addWatched, errorMessage, pickFolder } from "./watched";
import { XBOX_SUPPORT_URL } from "./XboxOnboarding";

export const GUIDES_URL = "https://github.com/heetdalsania/openworld-moments/tree/main/docs/guides";

const STEPS = ["welcome", "system", "import", "privacy", "display", "done"] as const;
type Step = (typeof STEPS)[number];
const TITLES: Record<Step, string> = {
  welcome: "Welcome to OpenWorld Moments",
  system: "Welcome — check this computer",
  import: "How your clips get here",
  privacy: "Privacy choices",
  display: "Display and motion",
  done: "You're ready",
};

/**
 * M31 first-run setup (spec 10.2): a few skippable steps that ask only what is needed now.
 * Every step can be skipped; choices are saved as they are made, and the whole setup can
 * be run again from Settings.
 */
export function Onboarding({
  workerReady,
  onImport,
}: {
  workerReady: boolean;
  onImport: () => void;
}) {
  const [step, setStep] = useState<Step>("welcome");
  const heading = useRef<HTMLHeadingElement>(null);
  const shown = useRef<Step>(step);
  const id = useId();
  const index = STEPS.indexOf(step);
  useEffect(() => {
    // Move focus to a new step's heading so keyboard and screen-reader users start there
    // (not on first display, where focus stays where the user left it).
    if (shown.current === step) return;
    shown.current = step;
    heading.current?.focus();
  }, [step]);

  const next = () => setStep(STEPS[Math.min(index + 1, STEPS.length - 1)] ?? "done");
  const back = () => setStep(STEPS[Math.max(index - 1, 0)] ?? "welcome");
  const finish = (state: "completed" | "skipped") => setOnboarding(state);

  return (
    <section className="view onboarding-flow" aria-labelledby={`${id}-heading`}>
      <p className="eyebrow" id={`${id}-progress`}>
        Setup · step {index + 1} of {STEPS.length}
      </p>
      <h1 id={`${id}-heading`} ref={heading} tabIndex={-1}>
        {TITLES[step]}
      </h1>
      <ol className="setup-steps" aria-label="Setup steps">
        {STEPS.map((s, i) => (
          <li key={s} aria-current={s === step ? "step" : undefined}>
            <span className="setup-step-state">
              {i < index ? "Done" : s === step ? "Current" : "Next"}
            </span>{" "}
            {TITLES[s]}
          </li>
        ))}
      </ol>

      {step === "welcome" && <Welcome />}
      {step === "system" &&
        (workerReady ? (
          <SystemPanel heading="This computer" />
        ) : (
          <p role="status">
            The media worker is still starting. You can continue setup and run the check later from
            Settings.
          </p>
        ))}
      {step === "import" && <ImportMethods workerReady={workerReady} />}
      {step === "privacy" && <PrivacyChoices embedded />}
      {step === "display" && <AppearanceSettings embedded />}
      {step === "done" && (
        <div className="panel">
          <p>
            Import a clip to begin, or open the library. You can run this setup again, change
            privacy choices and save diagnostics from Settings.
          </p>
          <p>
            Step-by-step guides for Xbox, PlayStation, capture cards and troubleshooting are in the
            project documentation: <span className="url">{GUIDES_URL}</span>
          </p>
          <div className="row">
            <button
              type="button"
              className="primary"
              disabled={!workerReady}
              onClick={() => {
                finish("completed");
                onImport();
              }}
            >
              Import a first clip
            </button>
            <button type="button" onClick={() => finish("completed")}>
              Go to the library
            </button>
          </div>
        </div>
      )}

      <nav className="row setup-nav" aria-label="Setup">
        {index > 0 && step !== "done" && (
          <button type="button" onClick={back}>
            Back
          </button>
        )}
        {step !== "done" && (
          <button type="button" className="primary" onClick={next}>
            {step === "welcome" ? "Start setup" : "Continue"}
          </button>
        )}
        {step !== "done" && (
          <button type="button" onClick={() => finish("skipped")}>
            Skip setup
          </button>
        )}
      </nav>
    </section>
  );
}

function Welcome() {
  return (
    <div className="panel">
      <p>
        OpenWorld Moments turns your gameplay recordings into sessions, highlights and short videos,
        on this computer.
      </p>
      <ul>
        <li>
          <strong>It works only with video files you already have.</strong> It never connects to,
          runs on or changes your console, your games or your game accounts, and it does not read
          game memory or network traffic.
        </li>
        <li>
          <strong>Your footage stays here.</strong> Original files are never modified, there is no
          account to create, and nothing is uploaded.
        </li>
        <li>
          <strong>Suggestions are drafts.</strong> Detected moments show their evidence and
          confidence, and you review and correct them.
        </li>
      </ul>
      <p className="muted">
        Setup takes a few minutes. Every step can be skipped and changed later in Settings.
      </p>
    </div>
  );
}

function ImportMethods({ workerReady }: { workerReady: boolean }) {
  const [mode, setMode] = useState<ImportMode>(savedMode);
  const [xbox, setXbox] = useState<string | null>(null);
  const name = useId();
  async function chooseXbox() {
    setXbox(null);
    const path = await pickFolder("Choose the OneDrive folder with your Xbox captures");
    if (path === null) return;
    try {
      await addWatched(path, "xbox");
      setXbox("Your Xbox captures folder is now watched. New clips import automatically.");
    } catch (error) {
      setXbox(`That folder could not be added: ${errorMessage(error)}`);
    }
  }
  return (
    <div className="panel">
      <ul className="methods">
        <li>
          <strong>Files and folders on this computer:</strong> use <em>Import</em> at the top, or
          drop videos onto the window. Works for capture-card and PC recordings too.
        </li>
        <li>
          <strong>Xbox:</strong> Xbox can back up captures to OneDrive. Keep that OneDrive folder on
          this computer and choose it here; OpenWorld Moments watches it and never connects to Xbox
          or OneDrive. ({XBOX_SUPPORT_URL})
          <div className="row">
            <button type="button" disabled={!workerReady} onClick={() => void chooseXbox()}>
              Choose Xbox captures folder…
            </button>
          </div>
          {xbox && <p role="status">{xbox}</p>}
        </li>
        <li>
          <strong>PlayStation:</strong> download clips to your phone with the PlayStation App, then
          send them here with <em>Import from phone</em>. That needs phone transfer, which you can
          allow on the next step.
        </li>
        <li>
          <strong>Folders that fill up on their own</strong> (capture software, synced drives): add
          them under Settings → Watched folders.
        </li>
      </ul>
      <fieldset>
        <legend>When you import, by default:</legend>
        <label className="check">
          <input
            type="radio"
            name={name}
            checked={mode === "reference"}
            onChange={() => {
              setMode("reference");
              saveMode("reference");
            }}
          />
          Keep files where they are (reference): uses no extra space; the original must stay
          available
        </label>
        <label className="check">
          <input
            type="radio"
            name={name}
            checked={mode === "managed"}
            onChange={() => {
              setMode("managed");
              saveMode("managed");
            }}
          />
          Copy into the library (managed): uses more space; safe if the original is moved
        </label>
      </fieldset>
    </div>
  );
}
