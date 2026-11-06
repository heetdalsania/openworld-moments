// SPDX-License-Identifier: AGPL-3.0-or-later
//! Watched-folder include/exclude patterns. Same rules as the worker
//! (`openworld_moments/watched/patterns.py`); both run the shared cases in
//! `packages/contracts/fixtures/watched-folder/patterns.json`.
//!
//! * Paths are '/'-separated and relative to the folder; matching ignores case.
//! * A pattern without '/' matches the file name; one with '/' the whole path.
//! * `*` and `?` stay within one segment; `**` as a whole segment spans any
//!   number of segments (inside a segment it acts like `*`).
//! * Only supported video extensions are candidates; an empty include list
//!   means every such file.

/// Kept equal to `VIDEO_EXTENSIONS` in `openworld_moments/media/probe.py`.
pub const VIDEO_EXTENSIONS: &[&str] = &[
    "mp4", "m4v", "mov", "mkv", "webm", "ts", "m2ts", "mts", "avi", "flv", "3gp",
];

/// Same rule as Python's `PurePosixPath.suffix`: the last '.' must be neither
/// the first nor the last character of the file name.
pub fn has_video_extension(relative_path: &str) -> bool {
    let name = relative_path.rsplit('/').next().unwrap_or(relative_path);
    match name.rfind('.') {
        Some(i) if i > 0 && i + 1 < name.len() => {
            VIDEO_EXTENSIONS.contains(&name[i + 1..].to_ascii_lowercase().as_str())
        }
        _ => false,
    }
}

pub fn is_candidate(relative_path: &str, include: &[String], exclude: &[String]) -> bool {
    if !has_video_extension(relative_path) {
        return false;
    }
    if !include.is_empty() && !include.iter().any(|p| matches(p, relative_path)) {
        return false;
    }
    !exclude.iter().any(|p| matches(p, relative_path))
}

pub fn matches(pattern: &str, relative_path: &str) -> bool {
    let pattern = pattern.to_lowercase();
    let path = relative_path.to_lowercase();
    if !pattern.contains('/') {
        let name = path.rsplit('/').next().unwrap_or(&path);
        return segment_matches(&pattern, name);
    }
    let p: Vec<&str> = pattern.split('/').collect();
    let s: Vec<&str> = path.split('/').collect();
    segments_match(&p, &s)
}

fn segments_match(pattern: &[&str], path: &[&str]) -> bool {
    match pattern.split_first() {
        None => path.is_empty(),
        Some((&"**", rest)) => (0..=path.len()).any(|k| segments_match(rest, &path[k..])),
        Some((first, rest)) => match path.split_first() {
            Some((head, tail)) => segment_matches(first, head) && segments_match(rest, tail),
            None => false,
        },
    }
}

/// `*` (and `**` inside a segment) matches any run of characters, `?` one character.
fn segment_matches(pattern: &str, text: &str) -> bool {
    let p: Vec<char> = pattern.chars().collect();
    let t: Vec<char> = text.chars().collect();
    let (mut pi, mut ti) = (0usize, 0usize);
    let mut star: Option<(usize, usize)> = None;
    while ti < t.len() {
        if pi < p.len() && (p[pi] == '?' || p[pi] == t[ti]) {
            pi += 1;
            ti += 1;
        } else if pi < p.len() && p[pi] == '*' {
            while pi < p.len() && p[pi] == '*' {
                pi += 1;
            }
            star = Some((pi, ti));
        } else if let Some((sp, st)) = star {
            pi = sp;
            ti = st + 1;
            star = Some((sp, st + 1));
        } else {
            return false;
        }
    }
    while pi < p.len() && p[pi] == '*' {
        pi += 1;
    }
    pi == p.len()
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::Value;

    const CASES: &str =
        include_str!("../../../../../packages/contracts/fixtures/watched-folder/patterns.json");

    fn strings(v: &Value) -> Vec<String> {
        v.as_array()
            .unwrap()
            .iter()
            .map(|s| s.as_str().unwrap().to_string())
            .collect()
    }

    #[test]
    fn shared_pattern_cases() {
        let doc: Value = serde_json::from_str(CASES).unwrap();
        for case in doc["cases"].as_array().unwrap() {
            let path = case["path"].as_str().unwrap();
            let got = is_candidate(path, &strings(&case["include"]), &strings(&case["exclude"]));
            assert_eq!(got, case["candidate"].as_bool().unwrap(), "case {case}");
        }
    }

    #[test]
    fn segment_wildcards() {
        assert!(segment_matches("clip-??.mp4", "clip-01.mp4"));
        assert!(!segment_matches("clip-??.mp4", "clip-1.mp4"));
        assert!(segment_matches("*a*b*", "xaybz"));
        assert!(!segment_matches("*a*b", "xaybz"));
        assert!(segment_matches("", ""));
    }

    #[test]
    fn extensions() {
        assert!(has_video_extension("a/b/Clip.MP4"));
        assert!(!has_video_extension("clip.mp4.part"));
        assert!(!has_video_extension("mp4"));
        assert!(!has_video_extension(".mp4")); // no suffix, like Python
        assert!(has_video_extension(".hidden.mp4")); // excluded by the default patterns
    }
}
