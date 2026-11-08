// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState, useSyncExternalStore } from "react";
import { describeError, listProjects } from "./api";
import { useQuery } from "./query";
import { routeHref } from "./route";
import { dirtyProjects, subscribeWorkspaces, workspaceSnapshot } from "./projectWorkspace";

export function ProjectsView({ workerReady }: { workerReady: boolean }) {
  useSyncExternalStore(subscribeWorkspaces, workspaceSnapshot);
  const [offset, setOffset] = useState(0);
  const projects = useQuery(workerReady ? `projects:${offset}` : null, () => listProjects(offset));
  const drafts = dirtyProjects();
  return (
    <section className="view" aria-labelledby="projects-heading">
      <div className="view-head">
        <div>
          <p className="eyebrow">CREATE / EDIT</p>
          <h1 id="projects-heading">Your projects</h1>
        </div>
        <a className="button primary" href="#/sessions">
          Create from a session
        </a>
      </div>
      <p className="muted">
        Trim a story, keep the context. Your original captures stay untouched.
      </p>
      {drafts.length > 0 && (
        <section className="notice-box" aria-label="Unsaved drafts">
          <h2>Unsaved in this window</h2>
          {drafts.map((d) => (
            <p key={d.id}>
              <a href={routeHref({ view: "project", id: d.id })}>{d.title}</a> · edits kept locally
              in this window
            </p>
          ))}
        </section>
      )}
      {!workerReady && (
        <p role="status">The worker is offline. Open drafts above remain available.</p>
      )}
      {projects.error && (
        <div role="alert">
          <p>{describeError(projects.error)}</p>
          <button onClick={projects.refetch}>Try again</button>
        </div>
      )}
      {projects.loading && <p role="status">Loading projects…</p>}
      {projects.data?.items.length === 0 && (
        <p>No projects yet. Open a session and choose a range to edit.</p>
      )}
      <div className="project-grid">
        {projects.data?.items.map((p) => (
          <a className="project-card" key={p.id} href={routeHref({ view: "project", id: p.id })}>
            <span className="project-card-icon" aria-hidden="true">
              ▰
            </span>
            <h2>{p.title}</h2>
            <p className="muted">
              {p.revision === 0 ? "Story draft · ready to edit" : `Saved revision ${p.revision}`}
            </p>
            <span>Open editor →</span>
          </a>
        ))}
      </div>
      {projects.data && projects.data.total > 50 && (
        <div className="row">
          <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))}>
            Previous projects
          </button>
          <span>
            {offset + 1}–{offset + projects.data.items.length} of {projects.data.total}
          </span>
          <button
            disabled={offset + 50 >= projects.data.total}
            onClick={() => setOffset(offset + 50)}
          >
            Next projects
          </button>
        </div>
      )}
    </section>
  );
}
