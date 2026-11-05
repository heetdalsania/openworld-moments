# Licensing

OpenWorld Moments uses a split license so the application stays open while its
schemas remain easy to adopt. Full texts live in [`LICENSES/`](./LICENSES/).

| Path | License | SPDX identifier |
|---|---|---|
| Application and worker: `apps/`, `services/`, `packages/ui/`, `packages/timeline/`, `scripts/`, and all other code unless listed below | GNU Affero General Public License v3.0 or later | `AGPL-3.0-or-later` |
| Event, profile, and integration schemas and SDKs: `packages/contracts/`, `profiles/` | Apache License 2.0 | `Apache-2.0` |
| Documentation: `docs/`, and Markdown files such as this one, `README.md`, and the build specification | Creative Commons Attribution 4.0 International | `CC-BY-4.0` |
| Small configuration files (lockfiles, editor and tool settings) | CC0 1.0 Universal | `CC0-1.0` |

The machine-readable source of truth is [`REUSE.toml`](./REUSE.toml), checked
by `pnpm lint:licenses`. A file's own `SPDX-License-Identifier` header takes
precedence over `REUSE.toml`.

See [docs/contributing/licensing.md](./docs/contributing/licensing.md) for how
to label new files.

Grand Theft Auto, GTA, GTA VI, and Rockstar Games are trademarks of their
respective owners. This project is unofficial and unaffiliated.
