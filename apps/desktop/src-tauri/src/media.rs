// SPDX-License-Identifier: AGPL-3.0-or-later
//! The UI's two ways into the worker (M09), both kept free of Tauri types so they are
//! testable:
//!
//! * [`api_route_allowed`]: the routes the UI may call through `worker_api`. Anything
//!   else (shutdown, cleanup, the host-only media lookup, ...) is refused, and the
//!   worker token never reaches the web view.
//! * [`serve`]: the `owm-media://` protocol. The player asks for
//!   `/asset/<asset-id>/<variant>[/<n>]`; the host asks the worker where that file is
//!   (`GET /v1/assets/{id}/media/{variant}`), then streams it with HTTP Range
//!   support. The web view never sends or sees a filesystem path, and nothing is
//!   ever written.

use std::io::SeekFrom;

use serde_json::{Value, json};
use tokio::io::{AsyncReadExt, AsyncSeekExt};

use crate::worker::{Supervisor, SupervisorError};

/// Custom protocol name. URLs are `owm-media://localhost/...` (macOS, Linux) or
/// `http://owm-media.localhost/...` (Windows).
pub const SCHEME: &str = "owm-media";
/// Largest body sent for one request; players ask for the rest with further ranges.
pub const MAX_CHUNK: u64 = 4 * 1024 * 1024;
/// Files up to this size are sent whole when no range is requested.
pub const WHOLE_LIMIT: u64 = 16 * 1024 * 1024;

fn is_id(segment: &str, prefix: &str) -> bool {
    segment.len() == prefix.len() + 26
        && segment.starts_with(prefix)
        && segment[prefix.len()..]
            .bytes()
            .all(|b| b.is_ascii_digit() || (b.is_ascii_uppercase() && !b"ILOU".contains(&b)))
}

fn query_ok(query: &str) -> bool {
    query.len() <= 256
        && query
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"_=&-".contains(&b))
}

/// Whether the UI may send `method path` to the worker.
pub fn api_route_allowed(method: &str, path: &str) -> bool {
    let (route, query) = match path.split_once('?') {
        Some((route, query)) => (route, Some(query)),
        None => (path, None),
    };
    if query.is_some_and(|q| !query_ok(q)) {
        return false;
    }
    let segments: Vec<&str> = route.split('/').collect();
    match (method, segments.as_slice()) {
        ("GET", ["", "v1", "capabilities"]) => true,
        ("GET", ["", "v1", "assets"]) | ("GET", ["", "v1", "jobs"]) => true,
        ("POST", ["", "v1", "imports"]) => query.is_none(),
        ("POST", ["", "v1", "assets", "check-sources"]) => query.is_none(),
        ("GET", ["", "v1", "assets", id]) => is_id(id, "ast_") && query.is_none(),
        ("GET" | "POST", ["", "v1", "assets", id, "derived"]) => {
            is_id(id, "ast_") && query.is_none()
        }
        ("GET", ["", "v1", "imports", id]) | ("GET", ["", "v1", "jobs", id]) => {
            is_id(id, "job_") && query.is_none()
        }
        ("POST", ["", "v1", "jobs", id, "cancel" | "retry"]) => {
            is_id(id, "job_") && query.is_none()
        }
        // Calibration (M15), data-only profile routes. No catalog filesystem access.
        ("GET", ["", "v1", "profiles"]) => query.is_none(),
        ("GET" | "PUT", ["", "v1", "profiles", id, "calibration"])
        | ("POST", ["", "v1", "profiles", id, "patch" | "reset" | "preview"]) => {
            !id.is_empty()
                && id.len() <= 128
                && id
                    .bytes()
                    .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-')
                && query.is_none()
        }
        ("GET", ["", "v1", "projects"]) => true,
        ("GET", ["", "v1", "sessions", id, "project-selection"]) => {
            is_id(id, "ses_") && query.is_none()
        }
        // M21: editor documents only; no filesystem paths or renderer commands.
        ("POST", ["", "v1", "projects", "import"]) => query.is_none(),
        ("GET" | "PUT", ["", "v1", "projects", id]) => is_id(id, "prj_") && query.is_none(),
        ("GET", ["", "v1", "projects", id, "portable"]) => is_id(id, "prj_") && query.is_none(),
        ("POST", ["", "v1", "sessions", id, "projects"]) => is_id(id, "ses_") && query.is_none(),
        ("POST", ["", "v1", "projects", id, "relink"]) => is_id(id, "prj_") && query.is_none(),
        // M24: renders write only inside the library; the UI never names an output path.
        ("GET", ["", "v1", "render", "presets" | "encoders"]) => query.is_none(),
        ("POST", ["", "v1", "projects", id, "render"]) => is_id(id, "prj_") && query.is_none(),
        ("GET", ["", "v1", "projects", id, "renders"]) => is_id(id, "prj_") && query.is_none(),
        ("GET", ["", "v1", "renders", id]) => is_id(id, "job_") && query.is_none(),
        // M26: local search, derived index maintenance and collections. No paths or SQL.
        ("POST", ["", "v1", "search"]) => query.is_none(),
        ("GET", ["", "v1", "search", "index"]) => query.is_none() || query == Some("check=true"),
        ("DELETE", ["", "v1", "search", "index"]) => query.is_none(),
        ("POST", ["", "v1", "search", "index", "rebuild"]) => query.is_none(),
        ("GET" | "POST", ["", "v1", "collections"]) => query.is_none(),
        ("GET", ["", "v1", "collections", id]) => is_id(id, "col_"),
        ("PUT" | "DELETE", ["", "v1", "collections", id])
        | ("POST", ["", "v1", "collections", id, "items"]) => is_id(id, "col_") && query.is_none(),
        ("DELETE", ["", "v1", "collections", id, "items", item]) => {
            is_id(id, "col_")
                && (1..=12).contains(&item.len())
                && item.bytes().all(|b| b.is_ascii_digit())
                && !item.starts_with('0')
                && query.is_none()
        }
        // Sessions (M11-M13).
        ("GET", ["", "v1", "sessions"]) => true,
        ("POST", ["", "v1", "sessions", "recompute" | "align" | "merge"]) => query.is_none(),
        ("GET", ["", "v1", "sessions", id]) => is_id(id, "ses_") && query.is_none(),
        ("GET", ["", "v1", "sessions", id, "overlaps" | "corrections"]) => {
            is_id(id, "ses_") && query.is_none()
        }
        (
            "POST",
            [
                "",
                "v1",
                "sessions",
                id,
                "split" | "order" | "remove" | "confirm",
            ],
        ) => is_id(id, "ses_") && query.is_none(),
        ("PUT", ["", "v1", "sessions", id, "overlaps", asset]) => {
            is_id(id, "ses_") && is_id(asset, "ast_") && query.is_none()
        }
        // M19: local event inspection and append-only decisions.
        ("GET", ["", "v1", "sessions", id, "review" | "stories"]) => is_id(id, "ses_"),
        ("POST", ["", "v1", "sessions", id, "review" | "analyze" | "stories"]) => {
            is_id(id, "ses_") && query.is_none()
        }
        ("POST", ["", "v1", "sessions", id, "review", event]) => {
            is_id(id, "ses_") && is_id(event, "evt_") && query.is_none()
        }
        // M18: optional local transcription. Deleting a transcript removes derived text only.
        ("GET", ["", "v1", "transcription", "models"]) => query.is_none(),
        ("POST", ["", "v1", "sessions", id, "stories", candidate, "decision"]) => {
            is_id(id, "ses_") && is_id(candidate, "prj_") && query.is_none()
        }
        ("POST", ["", "v1", "sessions", id, "transcribe"]) => is_id(id, "ses_") && query.is_none(),
        ("GET" | "DELETE", ["", "v1", "sessions", id, "transcript"]) => {
            is_id(id, "ses_") && query.is_none()
        }
        _ => false,
    }
}

/// A parsed `owm-media` request.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MediaRequest {
    pub asset_id: String,
    pub variant: &'static str,
    pub index: Option<u32>,
}

/// `/asset/<asset-id>/{original|proxy|waveform}` or `/asset/<asset-id>/thumbnail/<n>`.
pub fn parse_media_path(path: &str) -> Option<MediaRequest> {
    let segments: Vec<&str> = path.split('/').collect();
    let (id, variant, index) = match segments.as_slice() {
        ["", "asset", id, "original"] => (*id, "original", None),
        ["", "asset", id, "proxy"] => (*id, "proxy", None),
        ["", "asset", id, "waveform"] => (*id, "waveform", None),
        ["", "asset", id, "thumbnail", n] => {
            let n: u32 = n.parse().ok().filter(|n| (1..=1000).contains(n))?;
            (*id, "thumbnail", Some(n))
        }
        _ => return None,
    };
    is_id(id, "ast_").then(|| MediaRequest {
        asset_id: id.to_string(),
        variant,
        index,
    })
}

/// The byte range to send: `(start, end_inclusive)`, or None when unsatisfiable.
/// Open-ended and oversized ranges are capped at [`MAX_CHUNK`].
pub fn parse_range(header: Option<&str>, size: u64) -> Option<(u64, u64)> {
    if size == 0 {
        return None;
    }
    let Some(header) = header else {
        let end = if size <= WHOLE_LIMIT {
            size - 1
        } else {
            MAX_CHUNK.min(size) - 1
        };
        return Some((0, end));
    };
    let spec = header.trim().strip_prefix("bytes=")?;
    if spec.contains(',') {
        return None; // multipart ranges are not supported
    }
    let (start, end) = spec.split_once('-')?;
    let (start, end) = match (start.trim(), end.trim()) {
        ("", suffix) => {
            let n: u64 = suffix.parse().ok().filter(|n| *n > 0)?;
            (size.saturating_sub(n), size - 1)
        }
        (start, "") => (start.parse().ok()?, size - 1),
        (start, end) => (start.parse().ok()?, end.parse::<u64>().ok()?.min(size - 1)),
    };
    if start > end || start >= size {
        return None;
    }
    Some((start, end.min(start + MAX_CHUNK - 1)))
}

/// A protocol response without Tauri types.
#[derive(Debug)]
pub struct MediaResponse {
    pub status: u16,
    pub headers: Vec<(&'static str, String)>,
    pub body: Vec<u8>,
}

fn error(status: u16, code: &str, message: &str) -> MediaResponse {
    MediaResponse {
        status,
        headers: vec![
            ("Content-Type", "application/json".into()),
            ("Access-Control-Allow-Origin", "*".into()),
        ],
        body: json!({ "code": code, "message": message })
            .to_string()
            .into_bytes(),
    }
}

/// Serve one `owm-media` request. Reads only the file the worker named.
pub async fn serve(supervisor: &Supervisor, path: &str, range: Option<&str>) -> MediaResponse {
    let Some(request) = parse_media_path(path) else {
        return error(400, "media.invalid_request", "Unknown media address.");
    };
    let mut lookup = format!("/v1/assets/{}/media/{}", request.asset_id, request.variant);
    if let Some(index) = request.index {
        lookup.push_str(&format!("?index={index}"));
    }
    let found = match supervisor
        .request(reqwest::Method::GET, &lookup, None, None)
        .await
    {
        Ok(found) => found,
        Err(SupervisorError::Http { status, body }) => {
            let code = body["code"].as_str().unwrap_or("media.unavailable");
            let message = body["message"]
                .as_str()
                .unwrap_or("The media file is not available.");
            return error(status, code, message);
        }
        Err(_) => return error(503, "worker.unavailable", "The worker is not running."),
    };
    let (Some(file), Some(content_type)) = (found["path"].as_str(), found["content_type"].as_str())
    else {
        return error(502, "media.invalid_response", "The worker gave no file.");
    };
    read_range(file, content_type, range).await
}

async fn read_range(file: &str, content_type: &str, range: Option<&str>) -> MediaResponse {
    let mut handle = match tokio::fs::File::open(file).await {
        Ok(handle) => handle,
        Err(_) => return error(404, "media.unreadable", "The file could not be opened."),
    };
    let size = match handle.metadata().await {
        Ok(meta) if meta.is_file() => meta.len(),
        _ => return error(404, "media.unreadable", "The file could not be read."),
    };
    let Some((start, end)) = parse_range(range, size) else {
        let mut response = error(
            416,
            "media.bad_range",
            "The requested range is not available.",
        );
        response
            .headers
            .push(("Content-Range", format!("bytes */{size}")));
        return response;
    };
    let length = end - start + 1;
    let mut body = vec![0u8; length as usize];
    let read = async {
        handle.seek(SeekFrom::Start(start)).await?;
        handle.read_exact(&mut body).await
    };
    if read.await.is_err() {
        return error(
            404,
            "media.unreadable",
            "The file changed while it was read.",
        );
    }
    let partial = range.is_some() || length < size;
    let mut headers = vec![
        ("Content-Type", content_type.to_string()),
        ("Content-Length", length.to_string()),
        ("Accept-Ranges", "bytes".into()),
        ("Cache-Control", "no-cache".into()),
        ("Access-Control-Allow-Origin", "*".into()),
    ];
    if partial {
        headers.push(("Content-Range", format!("bytes {start}-{end}/{size}")));
    }
    MediaResponse {
        status: if partial { 206 } else { 200 },
        headers,
        body,
    }
}

/// The UI-facing error for a refused `worker_api` route.
pub fn route_refused() -> Value {
    json!({
        "code": "request.not_allowed",
        "message": "The app cannot make this request.",
        "retryable": false
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    const ASSET: &str = "ast_01JCBQ00000000000000000001";
    const JOB: &str = "job_01JCBQ00000000000000000021";
    const SESSION: &str = "ses_01JCBQ00000000000000000002";
    const COLLECTION: &str = "col_01JCBQ00000000000000000061";

    #[test]
    fn only_listed_routes_are_allowed() {
        for (method, path) in [
            ("GET", "/v1/assets?order=newest&limit=60"),
            ("GET", &format!("/v1/assets/{ASSET}")),
            ("GET", &format!("/v1/assets/{ASSET}/derived")),
            ("POST", &format!("/v1/assets/{ASSET}/derived")),
            ("POST", "/v1/imports"),
            ("GET", &format!("/v1/jobs/{JOB}")),
            ("POST", &format!("/v1/jobs/{JOB}/cancel")),
            ("POST", &format!("/v1/jobs/{JOB}/retry")),
            ("GET", "/v1/jobs?limit=200"),
            ("GET", "/v1/capabilities"),
            ("POST", "/v1/projects/import"),
            ("GET", "/v1/projects?offset=0&limit=50"),
            ("GET", &format!("/v1/sessions/{SESSION}/project-selection")),
            ("POST", &format!("/v1/sessions/{SESSION}/projects")),
            ("GET", "/v1/projects/prj_01JCBQ00000000000000000003"),
            ("GET", "/v1/render/presets"),
            ("GET", "/v1/render/encoders"),
            ("POST", "/v1/projects/prj_01JCBQ00000000000000000003/render"),
            ("GET", "/v1/projects/prj_01JCBQ00000000000000000003/renders"),
            ("GET", &format!("/v1/renders/{JOB}")),
            ("POST", "/v1/search"),
            ("GET", "/v1/search/index"),
            ("GET", "/v1/search/index?check=true"),
            ("DELETE", "/v1/search/index"),
            ("POST", "/v1/search/index/rebuild"),
            ("GET", "/v1/collections"),
            ("POST", "/v1/collections"),
            ("GET", &format!("/v1/collections/{COLLECTION}")),
            (
                "GET",
                &format!("/v1/collections/{COLLECTION}?offset=50&limit=50"),
            ),
            ("PUT", &format!("/v1/collections/{COLLECTION}")),
            ("DELETE", &format!("/v1/collections/{COLLECTION}")),
            ("POST", &format!("/v1/collections/{COLLECTION}/items")),
            ("DELETE", &format!("/v1/collections/{COLLECTION}/items/42")),
            ("PUT", "/v1/projects/prj_01JCBQ00000000000000000003"),
            (
                "GET",
                "/v1/projects/prj_01JCBQ00000000000000000003/portable",
            ),
            ("POST", "/v1/projects/prj_01JCBQ00000000000000000003/relink"),
            ("GET", "/v1/sessions?limit=200"),
            ("GET", &format!("/v1/sessions/{SESSION}")),
            ("GET", &format!("/v1/sessions/{SESSION}/overlaps")),
            ("POST", "/v1/sessions/recompute"),
            ("POST", "/v1/sessions/align"),
            ("POST", "/v1/sessions/merge"),
            ("POST", &format!("/v1/sessions/{SESSION}/order")),
            ("POST", &format!("/v1/sessions/{SESSION}/split")),
            ("PUT", &format!("/v1/sessions/{SESSION}/overlaps/{ASSET}")),
            (
                "GET",
                &format!("/v1/sessions/{SESSION}/review?offset=0&limit=50"),
            ),
            ("POST", &format!("/v1/sessions/{SESSION}/review")),
            (
                "POST",
                &format!("/v1/sessions/{SESSION}/review/evt_01JCBQ00000000000000000003"),
            ),
            ("POST", &format!("/v1/sessions/{SESSION}/analyze")),
            ("POST", &format!("/v1/sessions/{SESSION}/stories")),
            (
                "GET",
                &format!("/v1/sessions/{SESSION}/stories?preset=short&include_history=true"),
            ),
            (
                "POST",
                &format!("/v1/sessions/{SESSION}/stories/prj_01JCBQ00000000000000000003/decision"),
            ),
            ("GET", "/v1/transcription/models"),
            ("POST", &format!("/v1/sessions/{SESSION}/transcribe")),
            ("GET", &format!("/v1/sessions/{SESSION}/transcript")),
            ("DELETE", &format!("/v1/sessions/{SESSION}/transcript")),
        ] {
            assert!(api_route_allowed(method, path), "{method} {path}");
        }
        for (method, path) in [
            ("POST", "/v1/shutdown"),
            (
                "GET",
                &format!("/v1/sessions/{SESSION}/review?path=/private"),
            ),
            ("POST", &format!("/v1/sessions/{SESSION}/review/evt_bad")),
            (
                "POST",
                &format!("/v1/sessions/{SESSION}/stories?force=true"),
            ),
            (
                "POST",
                &format!("/v1/sessions/{SESSION}/stories/prj_bad/decision"),
            ),
            ("DELETE", &format!("/v1/sessions/{SESSION}/stories")),
            ("PUT", "/v1/projects/prj_bad"),
            ("POST", &format!("/v1/sessions/{SESSION}/project-selection")),
            ("GET", "/v1/sessions/ses_bad/project-selection"),
            (
                "GET",
                &format!("/v1/sessions/{SESSION}/project-selection?path=x"),
            ),
            ("GET", "/v1/projects/prj_01JCBQ00000000000000000003?path=x"),
            ("DELETE", "/v1/projects/prj_01JCBQ00000000000000000003"),
            ("POST", "/v1/projects/import?confirm=true"),
            ("GET", "/v1/projects/prj_01JCBQ00000000000000000003/relink"),
            (
                "GET",
                &format!("/v1/sessions/{SESSION}/stories/prj_01JCBQ00000000000000000003/decision"),
            ),
            ("POST", &format!("/v1/sessions/{SESSION}/review?limit=50")),
            ("DELETE", &format!("/v1/sessions/{SESSION}/review")),
            (
                "PUT",
                &format!("/v1/sessions/{SESSION}/review/evt_01JCBQ00000000000000000003"),
            ),
            ("POST", "/v1/derived/cleanup"),
            ("GET", &format!("/v1/assets/{ASSET}/media/original")),
            ("DELETE", &format!("/v1/assets/{ASSET}")),
            ("GET", "/v1/assets/../shutdown"),
            ("GET", "/v1/assets/ast_bad"),
            ("GET", "/v1/assets?path=/etc/passwd"),
            ("GET", "/v1/assets?x=%2e%2e"),
            ("POST", "/v1/imports?mode=managed"),
            ("GET", &format!("/v1/jobs/{JOB}/../../shutdown")),
            ("POST", "/v1/watched-folders"),
            ("DELETE", &format!("/v1/sessions/{SESSION}")),
            ("PUT", &format!("/v1/sessions/{SESSION}/overlaps/{SESSION}")),
            ("POST", "/v1/sessions/recompute?max_gap_ms=1"),
            (
                "POST",
                "/v1/projects/prj_01JCBQ00000000000000000003/render?output=/tmp/x.mp4",
            ),
            ("POST", "/v1/projects/prj_bad/render"),
            ("PUT", "/v1/render/presets"),
            ("POST", "/v1/render/presets"),
            ("GET", "/v1/render/encoders?refresh=1"),
            ("GET", "/v1/renders/prj_01JCBQ00000000000000000003"),
            ("DELETE", &format!("/v1/renders/{JOB}")),
            ("GET", "/v1/renders"),
            ("GET", "/v1/search"),
            ("POST", "/v1/search?query=x"),
            ("GET", "/v1/search/index?check=1"),
            ("PUT", "/v1/search/index"),
            ("GET", "/v1/search/index/rebuild"),
            ("POST", "/v1/search/index/rebuild?force=true"),
            ("DELETE", "/v1/collections"),
            ("GET", "/v1/collections/col_bad"),
            ("GET", &format!("/v1/collections/{SESSION}")),
            ("PUT", &format!("/v1/collections/{COLLECTION}?name=x")),
            ("GET", &format!("/v1/collections/{COLLECTION}/items")),
            ("DELETE", &format!("/v1/collections/{COLLECTION}/items/0")),
            ("DELETE", &format!("/v1/collections/{COLLECTION}/items/012")),
            ("DELETE", &format!("/v1/collections/{COLLECTION}/items/x1")),
            (
                "DELETE",
                &format!("/v1/collections/{COLLECTION}/items/1234567890123"),
            ),
            ("GET", "/v1/renders"),
            ("GET", "/v1/sessions/ses_bad"),
            (
                "DELETE",
                &format!("/v1/sessions/{SESSION}/transcript?all=1"),
            ),
            ("DELETE", "/v1/sessions/ses_bad/transcript"),
            ("POST", "/v1/transcription/models"),
            ("GET", "/v1/transcription/models?path=/tmp"),
            (
                "POST",
                &format!("/v1/sessions/{SESSION}/transcribe?model=x"),
            ),
            ("PUT", &format!("/v1/sessions/{SESSION}/transcript")),
        ] {
            assert!(!api_route_allowed(method, path), "{method} {path}");
        }
    }

    #[test]
    fn media_paths_are_strict() {
        assert_eq!(
            parse_media_path(&format!("/asset/{ASSET}/proxy")),
            Some(MediaRequest {
                asset_id: ASSET.into(),
                variant: "proxy",
                index: None
            })
        );
        assert_eq!(
            parse_media_path(&format!("/asset/{ASSET}/thumbnail/3")).map(|r| r.index),
            Some(Some(3))
        );
        for bad in [
            "/asset/../../etc/passwd/original".to_string(),
            format!("/asset/{ASSET}/thumbnail/0"),
            format!("/asset/{ASSET}/thumbnail/x"),
            format!("/asset/{ASSET}/frames"),
            format!("/asset/{ASSET}/original/extra"),
            "/asset/ast_01JCBQ0000000000000000000I/original".to_string(),
            "/C:/Windows/win.ini".to_string(),
        ] {
            assert_eq!(parse_media_path(&bad), None, "{bad}");
        }
    }

    #[test]
    fn ranges() {
        let mib = 1024 * 1024;
        assert_eq!(parse_range(None, 1000), Some((0, 999)));
        assert_eq!(parse_range(None, 100 * mib), Some((0, MAX_CHUNK - 1)));
        assert_eq!(parse_range(Some("bytes=0-1"), 1000), Some((0, 1)));
        assert_eq!(parse_range(Some("bytes=500-"), 1000), Some((500, 999)));
        assert_eq!(parse_range(Some("bytes=-100"), 1000), Some((900, 999)));
        assert_eq!(parse_range(Some("bytes=900-5000"), 1000), Some((900, 999)));
        assert_eq!(
            parse_range(Some("bytes=0-"), 100 * mib),
            Some((0, MAX_CHUNK - 1))
        );
        for bad in [
            "bytes=1000-",
            "bytes=5-2",
            "items=0-1",
            "bytes=0-1,5-6",
            "bytes=-0",
        ] {
            assert_eq!(parse_range(Some(bad), 1000), None, "{bad}");
        }
        assert_eq!(parse_range(None, 0), None);
    }

    #[tokio::test]
    async fn reads_ranges_from_a_file() {
        let dir = tempfile::tempdir().unwrap();
        let file = dir.path().join("proxy.mp4");
        std::fs::write(&file, b"0123456789").unwrap();
        let path = file.to_str().unwrap();
        let whole = read_range(path, "video/mp4", None).await;
        assert_eq!(
            (whole.status, whole.body.as_slice()),
            (200, &b"0123456789"[..])
        );
        let part = read_range(path, "video/mp4", Some("bytes=2-4")).await;
        assert_eq!((part.status, part.body.as_slice()), (206, &b"234"[..]));
        assert!(
            part.headers
                .contains(&("Content-Range", "bytes 2-4/10".to_string()))
        );
        assert_eq!(
            read_range(path, "video/mp4", Some("bytes=20-"))
                .await
                .status,
            416
        );
        let missing = dir.path().join("gone.mp4");
        assert_eq!(
            read_range(missing.to_str().unwrap(), "video/mp4", None)
                .await
                .status,
            404
        );
    }
}
