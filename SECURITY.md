# Security Policy

## Supported versions

The project is currently in specification stage and has no supported release. Supported versions will be listed here once public artifacts exist.

## Reporting a vulnerability

Do not open a public issue for a vulnerability involving media parsing, FFmpeg invocation, path traversal, local API authentication, LAN uploads, model downloads, update signing, credential storage, or arbitrary code execution.

Until a dedicated security mailbox is configured, contact the repository owner privately through GitHub. Include:

- A concise description.
- Affected milestone, component, or version.
- Reproduction steps.
- Expected and actual behavior.
- Potential impact.
- Any suggested mitigation.

Do not include private gameplay footage, credentials, tokens, or personal data unless explicitly requested through a secure channel.

## Security boundaries

- Source footage is treated as untrusted input.
- The desktop API must bind only to loopback.
- Phone upload must be temporary, tokenized, and isolated from the desktop API.
- FFmpeg commands must use argument arrays rather than shell interpolation.
- Models and binaries must have verified checksums and documented licenses.
- Plugins are deferred until a permissions and isolation model exists.

