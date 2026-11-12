// SPDX-License-Identifier: Apache-2.0
// schema_version policy. See packages/contracts/VERSIONING.md. Mirrors versioning.py.
import { ContractVersionError } from "./errors.ts";

export interface SchemaVersion {
  major: number;
  minor: number;
}

/** Version every versioned contract is currently written at. Kept in sync with Python by a test. */
export const SUPPORTED_VERSION = { major: 1, minor: 25 } as const;

const VERSION = /^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$/;

export function formatVersion(v: SchemaVersion): string {
  return `${v.major}.${v.minor}`;
}

/** Return the document's version, or throw with an actionable message. */
export function checkVersion(contract: string, document: unknown): SchemaVersion {
  if (
    typeof document !== "object" ||
    document === null ||
    Array.isArray(document) ||
    !("schema_version" in document)
  ) {
    throw new ContractVersionError(contract, ["missing required 'schema_version'"]);
  }
  const raw = (document as { schema_version: unknown }).schema_version;
  const match = typeof raw === "string" ? VERSION.exec(raw) : null;
  if (!match) {
    throw new ContractVersionError(contract, [
      `malformed schema_version ${pyRepr(raw)}; expected 'MAJOR.MINOR' such as '1.0'`,
    ]);
  }
  const found = { major: Number(match[1]), minor: Number(match[2]) };
  const supported = SUPPORTED_VERSION;
  if (found.major < supported.major) {
    throw new ContractVersionError(contract, [
      `schema_version ${formatVersion(found)} is older than the supported ${supported.major}.x; ` +
        "migrate the file with the release that introduced the new format before opening it",
    ]);
  }
  if (found.major > supported.major || found.minor > supported.minor) {
    throw new ContractVersionError(contract, [
      `schema_version ${formatVersion(found)} was written by a newer OpenWorld Moments; this ` +
        `version reads up to ${formatVersion(supported)}. Update the app to open it`,
    ]);
  }
  return found;
}

// Match Python's repr() for the values a malformed version can take, so messages are identical.
function pyRepr(value: unknown): string {
  if (typeof value === "string") return `'${value}'`;
  if (value === null || value === undefined) return "None";
  if (typeof value === "boolean") return value ? "True" : "False";
  return JSON.stringify(value);
}
