// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from "react";
import {
  type ApiError,
  describeError,
  listAssets,
  type MediaAsset,
  PAGE_SIZE,
  toApiError,
} from "./api";
import { formatDuration, thumbnailUrl } from "./media";
import { useQuery } from "./query";
import { routeHref } from "./route";

interface Paging {
  base: MediaAsset[] | undefined;
  pages: MediaAsset[];
  busy: boolean;
  done: boolean;
  error?: ApiError;
}

const EMPTY_PAGING: Omit<Paging, "base"> = { pages: [], busy: false, done: false };

function Thumbnail({ asset }: { asset: MediaAsset }) {
  const [failed, setFailed] = useState(false);
  if (failed) return <span className="thumb placeholder play-symbol" aria-hidden="true" />;
  return (
    <img
      className="thumb"
      src={thumbnailUrl(asset.id)}
      alt=""
      loading="lazy"
      onError={() => setFailed(true)}
    />
  );
}

export function badges(asset: MediaAsset): string[] {
  const out: string[] = [];
  if (asset.missing_at) out.push("Original missing");
  if (asset.video?.color.hdr) out.push("HDR");
  if (!asset.audio || asset.audio.length === 0) out.push("No audio");
  if (asset.import_mode === "managed") out.push("Copied to library");
  return out;
}

function AssetCard({ asset }: { asset: MediaAsset }) {
  const tags = badges(asset);
  return (
    <li>
      <a className="card clip-card" href={routeHref({ view: "asset", id: asset.id })}>
        <span className="clip-preview">
          <Thumbnail asset={asset} />
          <span className="clip-play play-symbol" aria-hidden="true" />
        </span>
        <span className="clip-details">
          <span className="card-title" title={asset.original_name}>
            {asset.original_name}
          </span>
          <span className="muted">
            {formatDuration(asset.duration_ms)}
            {asset.video ? ` · ${asset.video.width}×${asset.video.height}` : ""}
          </span>
          {tags.length > 0 && (
            <span className="badges">
              {tags.map((tag) => (
                <span key={tag} className={tag === "Original missing" ? "badge warn" : "badge"}>
                  {tag}
                </span>
              ))}
            </span>
          )}
        </span>
      </a>
    </li>
  );
}

/**
 * The library: newest first, loaded in pages with a keyset cursor so pages stay stable
 * while new imports arrive (they appear at the top after a refresh).
 */
export function LibraryView({ onImport }: { onImport: () => void }) {
  const [layout, setLayout] = useState<"grid" | "list">("grid");
  const [search, setSearch] = useState("");
  const [order, setOrder] = useState("newest");
  const [filter, setFilter] = useState("all");
  const first = useQuery("assets:first", () => listAssets());
  // Extra pages belong to the first page they continue; a refreshed first page
  // (new imports) restarts paging.
  const [paging, setPaging] = useState<Paging>({
    base: undefined,
    pages: [],
    busy: false,
    done: false,
  });
  const current = paging.base === first.data ? paging : { ...EMPTY_PAGING, base: first.data };
  const more = current.pages;
  const moreState = current;

  const seen = new Set<string>();
  const assets = [...(first.data ?? []), ...more].filter((a) => !seen.has(a.id) && seen.add(a.id));
  const lastPageFull =
    more.length > 0 ? more.length % PAGE_SIZE === 0 : (first.data?.length ?? 0) === PAGE_SIZE;
  const canLoadMore = lastPageFull && !moreState.done;

  const term = search.trim().toLocaleLowerCase();
  const visible = assets.filter(
    (asset) =>
      asset.original_name.toLocaleLowerCase().includes(term) &&
      (filter === "all" ||
        (filter === "hdr" && asset.video?.color.hdr) ||
        (filter === "missing" && asset.missing_at) ||
        (filter === "managed" && asset.import_mode === "managed")),
  );
  if (order === "oldest") visible.reverse();
  if (order === "name")
    visible.sort((a, b) =>
      a.original_name.localeCompare(b.original_name, undefined, { numeric: true }),
    );
  if (order === "duration") visible.sort((a, b) => (b.duration_ms ?? 0) - (a.duration_ms ?? 0));

  async function loadMore() {
    const last = assets[assets.length - 1];
    if (!last) return;
    const base = first.data;
    setPaging({ ...current, busy: true, error: undefined });
    try {
      const page = await listAssets(last.id);
      setPaging({ base, pages: [...more, ...page], busy: false, done: page.length < PAGE_SIZE });
    } catch (error) {
      setPaging({ ...current, busy: false, error: toApiError(error) });
    }
  }

  return (
    <section aria-labelledby="library-heading" className="view library-view">
      <div className="view-head">
        <div>
          <h1 id="library-heading">Library</h1>
          <p className="muted">Browse and open your video clips.</p>
        </div>
        <button type="button" onClick={first.refetch} disabled={first.loading}>
          Refresh
        </button>
      </div>
      {first.loading && !first.data && (
        <>
          <p role="status" className="muted">
            Loading your library…
          </p>
          <div className="grid" aria-hidden="true">
            {Array.from({ length: 3 }, (_, index) => (
              <div key={index} className="clip-skeleton" />
            ))}
          </div>
        </>
      )}
      {first.error && (
        <div role="alert" className="notice-box">
          <p>The library could not be loaded: {describeError(first.error)}</p>
          <button type="button" onClick={first.refetch}>
            Try again
          </button>
        </div>
      )}
      {first.data && assets.length === 0 && (
        <div className="empty library-empty">
          <span className="feature-icon" aria-hidden="true">
            ▤
          </span>
          <h2>No clips yet</h2>
          <p>Import video files or folders to start your library. Your originals stay untouched.</p>
          <button type="button" className="primary" onClick={onImport}>
            Import media
          </button>
          <p className="muted">
            You can also watch a folder (for example your Xbox captures) in{" "}
            <a href={routeHref({ view: "settings" })}>Settings</a>.
          </p>
        </div>
      )}
      {assets.length > 0 && (
        <>
          <div className="library-tools">
            <label className="clip-search">
              <span aria-hidden="true">⌕</span>
              <input
                type="search"
                aria-label="Search clips by filename"
                placeholder="Search by filename…"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
            </label>
            <select
              aria-label="Filter clips"
              value={filter}
              onChange={(event) => setFilter(event.target.value)}
            >
              <option value="all">All clips</option>
              <option value="hdr">HDR</option>
              <option value="missing">Missing originals</option>
              <option value="managed">Copied to library</option>
            </select>
            <select
              aria-label="Sort clips"
              value={order}
              onChange={(event) => setOrder(event.target.value)}
            >
              <option value="newest">Newest first</option>
              <option value="oldest">Oldest first</option>
              <option value="name">Filename A–Z</option>
              <option value="duration">Longest first</option>
            </select>
            <div className="layout-picker" role="group" aria-label="Library layout">
              <button
                type="button"
                aria-pressed={layout === "grid"}
                onClick={() => setLayout("grid")}
              >
                Grid
              </button>
              <button
                type="button"
                aria-pressed={layout === "list"}
                onClick={() => setLayout("list")}
              >
                List
              </button>
            </div>
          </div>
          <p className="muted library-count" role="status">
            {visible.length} of {assets.length} {canLoadMore ? "loaded " : ""}
            {assets.length === 1 ? "clip" : "clips"}
          </p>
          {visible.length ? (
            <ul
              className={layout === "grid" ? "grid clip-grid" : "grid clip-list"}
              aria-label={`${visible.length} clips`}
            >
              {visible.map((asset) => (
                <AssetCard key={asset.id} asset={asset} />
              ))}
            </ul>
          ) : (
            <div className="empty library-empty">
              <h2>No matching clips</h2>
              <p>
                {canLoadMore
                  ? "Load more clips to expand these results."
                  : "Try another filename or filter."}
              </p>
              <button
                type="button"
                onClick={() => {
                  setSearch("");
                  setFilter("all");
                }}
              >
                Clear search and filter
              </button>
            </div>
          )}
        </>
      )}
      {moreState.error && (
        <p role="alert">More clips could not be loaded: {describeError(moreState.error)}</p>
      )}
      {canLoadMore && (
        <div className="row center">
          <button type="button" onClick={() => void loadMore()} disabled={moreState.busy}>
            {moreState.busy ? "Loading…" : "Load more"}
          </button>
        </div>
      )}
    </section>
  );
}
