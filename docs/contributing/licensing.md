# Licensing new files

The repository follows the [REUSE](https://reuse.software/) convention. Each
file's license is determined by, in order:

1. An `SPDX-License-Identifier` comment in the file itself.
2. The matching annotation in [`REUSE.toml`](../../REUSE.toml).

## Which license applies

- **Code** in `apps/`, `services/`, `packages/ui/`, `packages/timeline/`, and
  `scripts/`: `AGPL-3.0-or-later`.
- **Schemas, profiles, and integration SDKs** in `packages/contracts/` and
  `profiles/`: `Apache-2.0`.
- **Documentation** (`docs/` and Markdown): `CC-BY-4.0`.
- **Trivial configuration** (lockfiles, editor/tool config): `CC0-1.0`.

## Headers

Add a one-line SPDX header to new source files:

```rust
// SPDX-License-Identifier: AGPL-3.0-or-later
```

```python
# SPDX-License-Identifier: AGPL-3.0-or-later
```

```ts
// Inside packages/contracts/:
// SPDX-License-Identifier: Apache-2.0
```

JSON and other formats without comments rely on `REUSE.toml`. If you add a new
top-level directory, add or confirm its annotation there.

## Checking

```bash
pnpm lint:licenses
```

## Contributions and sign-off

Contributions are accepted under the license of the files they touch and must
carry a Developer Certificate of Origin sign-off (`git commit -s`). CI rejects
pull requests with unsigned commits. See <https://developercertificate.org/>.

## Third-party material

Do not add third-party code, media, models, or fonts without recording their
license. Game assets and leaked footage are never accepted.
