// SPDX-License-Identifier: AGPL-3.0-or-later
use std::collections::VecDeque;

/// Keeps the last `max_bytes` of a process's stderr, redacting secrets on read.
#[derive(Debug)]
pub struct BoundedTail {
    max_bytes: usize,
    lines: VecDeque<String>,
    size: usize,
    truncated: bool,
    secrets: Vec<String>,
}

impl BoundedTail {
    pub fn new(max_bytes: usize, secrets: Vec<String>) -> Self {
        Self {
            max_bytes: max_bytes.max(64),
            lines: VecDeque::new(),
            size: 0,
            truncated: false,
            secrets: secrets.into_iter().filter(|s| s.len() >= 8).collect(),
        }
    }

    pub fn push_line(&mut self, line: &str) {
        let mut line = format!("{line}\n");
        if line.len() > self.max_bytes {
            let cut = line.len() - self.max_bytes;
            let boundary = (cut..line.len())
                .find(|i| line.is_char_boundary(*i))
                .unwrap_or(line.len());
            line = line[boundary..].to_string();
            self.truncated = true;
        }
        self.size += line.len();
        self.lines.push_back(line);
        while self.size > self.max_bytes {
            match self.lines.pop_front() {
                Some(old) => {
                    self.size -= old.len();
                    self.truncated = true;
                }
                None => break,
            }
        }
    }

    /// Redacted text, prefixed with a marker when earlier output was dropped.
    pub fn text(&self) -> String {
        let mut text: String = self.lines.iter().map(String::as_str).collect();
        if self.truncated {
            text.insert_str(0, "[earlier output truncated]\n");
        }
        for secret in &self.secrets {
            text = text.replace(secret.as_str(), "[redacted]");
        }
        redact_bearer(&text)
    }
}

fn redact_bearer(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    let mut rest = text;
    while let Some(pos) = rest.to_ascii_lowercase().find("bearer ") {
        let (head, tail) = rest.split_at(pos + "bearer ".len());
        out.push_str(head);
        let end = tail
            .find(|c: char| c.is_whitespace() || c == '"' || c == '\'')
            .unwrap_or(tail.len());
        out.push_str("[redacted]");
        rest = &tail[end..];
    }
    out.push_str(rest);
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn keeps_only_the_end_and_redacts() {
        let mut tail = BoundedTail::new(80, vec!["supersecret123".into()]);
        for i in 0..40 {
            tail.push_line(&format!("line {i} supersecret123 Bearer abc.def"));
        }
        let text = tail.text();
        assert!(text.starts_with("[earlier output truncated]"));
        assert!(text.contains("line 39"));
        assert!(!text.contains("line 0 "));
        assert!(!text.contains("supersecret123"));
        assert!(!text.contains("abc.def"));
        assert!(text.contains("Bearer [redacted]"));
    }

    #[test]
    fn truncates_a_single_huge_line_on_a_char_boundary() {
        let mut tail = BoundedTail::new(64, vec![]);
        tail.push_line(&"é".repeat(1000));
        assert!(tail.text().len() <= 64 + "[earlier output truncated]\n".len());
    }
}
