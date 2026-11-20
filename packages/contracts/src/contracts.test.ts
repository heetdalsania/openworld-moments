// SPDX-License-Identifier: Apache-2.0
// Shared fixtures: the Python suite runs the same files with the same expectations.
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it, vi } from "vitest";
import { ContractError, ContractVersionError } from "./errors.ts";
import { CONTRACTS, load, normalize, type ContractName } from "./validate.ts";
import { checkVersion } from "./versioning.ts";

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const fixtures = path.join(root, "fixtures");

interface InvalidCase {
  description: string;
  expect: "version" | "schema" | "semantic";
  path?: string;
  message_contains?: string;
  document: unknown;
}

function cases(kind: "valid" | "invalid"): [ContractName, string, unknown][] {
  return readdirSync(fixtures)
    .sort()
    .flatMap((contract) => {
      const dir = path.join(fixtures, contract, kind);
      return readdirSync(dir)
        .filter((f) => f.endsWith(".json"))
        .sort()
        .map((f): [ContractName, string, unknown] => [
          contract as ContractName,
          f.replace(/\.json$/, ""),
          JSON.parse(readFileSync(path.join(dir, f), "utf8")),
        ]);
    });
}

describe("valid fixtures", () => {
  it.each(cases("valid"))("%s/%s parses to its canonical input", (contract, _name, raw) => {
    expect(normalize(load(contract, raw))).toStrictEqual(normalize(raw));
  });
});

describe("invalid fixtures", () => {
  it.each(cases("invalid"))("%s/%s is rejected for the stated reason", (contract, _name, raw) => {
    const c = raw as InvalidCase;
    let caught: unknown;
    try {
      load(contract, c.document);
    } catch (err) {
      caught = err;
    }
    expect(caught).toBeInstanceOf(ContractError);
    const err = caught as ContractError;
    expect(err instanceof ContractVersionError).toBe(c.expect === "version");
    const fragment = c.message_contains;
    if (fragment) {
      expect(
        err.issues.some((i) => i.includes(fragment)),
        err.issues.join("\n"),
      ).toBe(true);
    }
    const prefix = c.path;
    if (prefix) {
      const paths = err.issues.map((i) => i.split(": ")[0] ?? i);
      expect(
        paths.some((p) => p.startsWith(prefix)),
        paths.join("\n"),
      ).toBe(true);
    }
  });
});

describe("load order", () => {
  // Each contract must load as the very first one in a fresh module, so cross-file $refs never
  // depend on another contract having been loaded earlier.
  it.each(Object.keys(CONTRACTS))("%s loads first in a fresh module", async (contract) => {
    vi.resetModules();
    const fresh = await import("./validate.ts");
    const dir = path.join(fixtures, contract, "valid");
    const first = readdirSync(dir).sort()[0];
    expect(first, `${contract} has no valid fixture`).toBeDefined();
    const raw: unknown = JSON.parse(readFileSync(path.join(dir, first ?? ""), "utf8"));
    expect(() => fresh.load(contract as ContractName, raw)).not.toThrow();
  });
});

describe("coverage", () => {
  it("every contract has valid and invalid fixtures", () => {
    for (const contract of Object.keys(CONTRACTS)) {
      for (const kind of ["valid", "invalid"]) {
        expect(
          readdirSync(path.join(fixtures, contract, kind)).length,
          `${contract}/${kind}`,
        ).toBeGreaterThan(0);
      }
    }
  });
});

describe("checkVersion", () => {
  it.each([
    [{}, "missing"],
    [{ schema_version: 1 }, "malformed schema_version 1;"],
    [{ schema_version: "0.9" }, "older than the supported 1.x"],
    [{ schema_version: "1.28" }, "reads up to 1.27"],
    [{ schema_version: "2.0" }, "newer OpenWorld Moments"],
  ])("rejects %j with a useful message", (doc, fragment) => {
    expect(() => checkVersion("event", doc)).toThrow(fragment);
  });

  it.each([
    ["1.0", 0],
    ["1.1", 1],
    ["1.2", 2],
    ["1.3", 3],
    ["1.4", 4],
    ["1.5", 5],
    ["1.6", 6],
    ["1.7", 7],
    ["1.8", 8],
    ["1.9", 9],
    ["1.10", 10],
    ["1.11", 11],
    ["1.12", 12],
    ["1.13", 13],
    ["1.14", 14],
    ["1.15", 15],
    ["1.16", 16],
    ["1.17", 17],
    ["1.18", 18],
    ["1.19", 19],
    ["1.20", 20],
    ["1.21", 21],
    ["1.22", 22],
  ])("accepts supported version %s", (version, minor) => {
    expect(checkVersion("event", { schema_version: version })).toEqual({ major: 1, minor });
  });
});
