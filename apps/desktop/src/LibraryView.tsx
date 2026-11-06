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
  if (failed) return <div className="thumb placeholder" aria-hidden="true" />;
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
      <a className="card" href={routeHref({ view: "asset", id: asset.id })}>
        <Thumbnail asset={asset} />
        <span className="card-title">{asset.original_name}</span>
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
      </a>
    </li>
  );
}

/**
 * The library: newest first, loaded in pages with a keyset cursor so pages stay stable
 * while new imports arrive (they appear at the top after a refresh).
 */
export function LibraryView({ onImport }: { onImport: () => void }) {
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
    <section aria-labelledby="library-heading" className="view">
      <div className="view-head">
        <h1 id="library-heading">Library</h1>
        <button type="button" onClick={first.refetch} disabled={first.loading}>
          Refresh
        </button>
      </div>
      {first.loading && !first.data && <p role="status">Loading your library…</p>}
      {first.error && (
        <div role="alert" className="notice-box">
          <p>The library could not be loaded: {describeError(first.error)}</p>
          <button type="button" onClick={first.refetch}>
            Try again
          </button>
        </div>
      )}
      {first.data && assets.length === 0 && (
        <div className="empty">
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
        <ul className="grid" aria-label={`${assets.length} clips`}>
          {assets.map((asset) => (
            <AssetCard key={asset.id} asset={asset} />
          ))}
        </ul>
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
