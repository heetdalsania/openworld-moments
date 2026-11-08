// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from "react";
import { createProject, describeError, projectSelection } from "./api";
import { invalidate, useAction, useQuery } from "./query";
import { navigate } from "./route";

export function CreateProject({ sessionId, currentMs }: { sessionId: string; currentMs: number }) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("Untitled story");
  const [start, setStart] = useState("0"),
    [end, setEnd] = useState<string | null>(null);
  const selection = useQuery(open ? `project-selection:${sessionId}` : null, () =>
    projectSelection(sessionId),
  );
  const action = useAction(async () => {
    if (!selection.data) throw new Error("Refresh the session range first.");
    const state = await createProject(sessionId, {
      title,
      layout_key: selection.data.layout_key,
      start_ms: Number(start),
      end_ms: end === null ? selection.data.duration_ms : Number(end),
    });
    invalidate("projects");
    navigate({ view: "project", id: state.document.project.id });
  });
  return (
    <section className="create-project panel" aria-labelledby="create-project-heading">
      <h2 id="create-project-heading">Make a story from this session</h2>
      <p className="muted">
        Choose a range on the unique session timeline. No detector results needed.
      </p>
      {!open ? (
        <button className="primary" onClick={() => setOpen(true)}>
          Choose range to edit
        </button>
      ) : (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void action.run();
          }}
        >
          <div className="row">
            <label>
              Project title
              <input
                required
                maxLength={300}
                value={title}
                onChange={(e) => setTitle(e.target.value)}
              />
            </label>
            <label>
              Session in (ms)
              <input
                type="number"
                required
                min={0}
                step={1}
                value={start}
                onChange={(e) => setStart(e.target.value)}
              />
            </label>
            <label>
              Session out (ms)
              <input
                type="number"
                required
                min={1}
                step={1}
                max={selection.data?.duration_ms}
                value={end === null ? String(selection.data?.duration_ms ?? "") : end}
                onChange={(e) => setEnd(e.target.value)}
              />
            </label>
          </div>
          <div className="row">
            <button type="button" onClick={() => setStart(String(Math.round(currentMs)))}>
              Use playhead as in
            </button>
            <button type="button" onClick={() => setEnd(String(Math.round(currentMs)))}>
              Use playhead as out
            </button>
            <button className="primary" disabled={!selection.data || action.busy}>
              Create and edit
            </button>
            <button type="button" disabled={action.busy} onClick={() => setOpen(false)}>
              Cancel selection
            </button>
          </div>
          {selection.loading && <p role="status">Loading current session range…</p>}
          {selection.error && (
            <p role="alert">
              {describeError(selection.error)}{" "}
              <button type="button" onClick={selection.refetch}>
                Refresh range
              </button>
            </p>
          )}
          {action.error && (
            <p role="alert">
              {describeError(action.error)}{" "}
              <button type="button" onClick={selection.refetch}>
                Refresh range
              </button>
            </p>
          )}
        </form>
      )}
    </section>
  );
}
