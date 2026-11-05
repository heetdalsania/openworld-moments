# M10 — Phone QR upload

## Objective

Allow PlayStation App and other phone-downloaded clips to transfer directly to the desktop over a temporary, isolated local-network upload page.

## Dependencies

M05 and M09 merged.

## Required context

Read specification sections 6.2, 9.2.2, 14.1, and 14.2.

## In scope

- Explicit “Import from phone” desktop flow.
- Private-interface selection and public-network warning.
- High-entropy expiring upload token and QR code.
- Mobile-responsive multi-file page.
- Fixed staging directory, filename sanitation, media allowlist, and size limits.
- Immediate gateway shutdown and import handoff.
- Upload status on phone and desktop.

## Out of scope

- Native mobile app, cloud relay, background LAN server, and resumable chunks.

## Implementation steps

1. Implement a gateway process/service separate from desktop API.
2. Bind only while the import screen is active.
3. Encode address and token in QR; never include desktop API credentials.
4. Stream uploads to staging with bounded resources.
5. Validate media through M04/M05 before canonical import.
6. Expire token on timeout, stop, or successful session completion.
7. Add threat-focused tests and user documentation.

## Acceptance criteria

- Gateway is unreachable before activation and after closure.
- Invalid/expired tokens fail without revealing library data.
- Filenames cannot traverse outside staging.
- Unsupported files do not enter canonical storage.
- Phone can upload multiple supported files on a trusted LAN.
- Desktop displays the security limitation of tokenized HTTP.

## Required validation

- Real phone smoke test on Windows private network.
- Expiry, traversal, oversized, unsupported, interrupted, and duplicate upload tests.
- Port/interface selection test.

## Handoff

Document network model, token entropy/lifetime, limits, staging cleanup, and manual PS5 workflow. Update M10.

