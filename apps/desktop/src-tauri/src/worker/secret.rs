// SPDX-License-Identifier: AGPL-3.0-or-later
use std::fmt;

/// Per-launch bearer token. Never printed: `Debug` and `Display` are redacted.
#[derive(Clone, PartialEq, Eq)]
pub struct Token(String);

impl Token {
    /// 32 random bytes from the OS, hex-encoded (64 characters).
    pub fn generate() -> Result<Self, getrandom::Error> {
        let mut bytes = [0u8; 32];
        getrandom::fill(&mut bytes)?;
        Ok(Self(hex::encode(bytes)))
    }

    /// The secret value. Only for the worker's stdin and the Authorization header.
    pub fn expose(&self) -> &str {
        &self.0
    }
}

impl fmt::Debug for Token {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("Token([redacted])")
    }
}

impl fmt::Display for Token {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("[redacted]")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tokens_are_random_hex_and_never_formatted() {
        let a = Token::generate().unwrap();
        let b = Token::generate().unwrap();
        assert_ne!(a, b);
        assert_eq!(a.expose().len(), 64);
        assert!(a.expose().chars().all(|c| c.is_ascii_hexdigit()));
        assert!(!format!("{a:?} {a}").contains(a.expose()));
    }
}
