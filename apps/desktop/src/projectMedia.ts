// SPDX-License-Identifier: AGPL-3.0-or-later
import type { EditorProject } from "@openworld-moments/contracts";
import { getAsset, getDerived, type MediaAsset, type ProjectState } from "./api";
import { mediaUrl } from "./media";

export interface ProjectMedia {
  asset?: MediaAsset;
  url: string | null;
  usesProxy: boolean;
  filmstrip: number[];
  waveform: boolean;
  reason?: string;
}
export async function loadProjectMedia(
  document: EditorProject,
  availability: ProjectState["sources"],
): Promise<Record<string, ProjectMedia>> {
  const ids = new Set((document.project.tracks[0]?.segments ?? []).map((s) => s.asset_id));
  const results = await Promise.all(
    document.sources
      .filter((s) => ids.has(s.asset_id))
      .map(async (source) => {
        const empty: ProjectMedia = { url: null, usesProxy: false, filmstrip: [], waveform: false };
        if (source.requires_relink)
          return [
            source.asset_id,
            { ...empty, reason: "Choose a verified source binding before previewing." },
          ] as const;
        try {
          const [asset, derived] = await Promise.all([
            getAsset(source.asset_id),
            getDerived(source.asset_id).catch(() => undefined),
          ]);
          if (asset.sha256 !== source.sha256 || asset.duration_ms !== source.duration_ms)
            return [
              source.asset_id,
              { ...empty, reason: "Source identity differs. Relink before previewing." },
            ] as const;
          const ready = (kind: string) =>
            derived?.artifacts.find((a) => a.kind === kind && a.status === "ready");
          const usesProxy = Boolean(ready("proxy"));
          const original =
            availability?.some(
              (a) => a.asset_id === asset.id && a.state === "available_unverified",
            ) && !asset.missing_at;
          return [
            asset.id,
            {
              asset,
              usesProxy,
              url: usesProxy
                ? mediaUrl(asset.id, "proxy")
                : original
                  ? mediaUrl(asset.id, "original")
                  : null,
              filmstrip: ready("filmstrip")?.filmstrip?.times_ms ?? [],
              waveform: Boolean(ready("waveform")),
              ...(!usesProxy && !original
                ? { reason: "Original offline and no ready playback copy. Your edits are kept." }
                : {}),
            },
          ] as const;
        } catch {
          return [
            source.asset_id,
            { ...empty, reason: "Source details are unavailable. Your edits are kept." },
          ] as const;
        }
      }),
  );
  return Object.fromEntries(results);
}
