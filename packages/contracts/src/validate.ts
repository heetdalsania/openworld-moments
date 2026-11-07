// SPDX-License-Identifier: Apache-2.0
// Single entry point for reading contract documents: version → schema → semantics.
// Mirrors validate.py.
import { Ajv2020, type ErrorObject, type ValidateFunction } from "ajv/dist/2020.js";
import common from "../schemas/common.schema.json" with { type: "json" };
import derivedMedia from "../schemas/derived-media.schema.json" with { type: "json" };
import error from "../schemas/error.schema.json" with { type: "json" };
import event from "../schemas/event.schema.json" with { type: "json" };
import evidence from "../schemas/evidence.schema.json" with { type: "json" };
import exportManifest from "../schemas/export-manifest.schema.json" with { type: "json" };
import fingerprint from "../schemas/fingerprint.schema.json" with { type: "json" };
import importResult from "../schemas/import.schema.json" with { type: "json" };
import jobEvent from "../schemas/job-event.schema.json" with { type: "json" };
import job from "../schemas/job.schema.json" with { type: "json" };
import mediaAsset from "../schemas/media-asset.schema.json" with { type: "json" };
import overlap from "../schemas/overlap.schema.json" with { type: "json" };
import profile from "../schemas/profile.schema.json" with { type: "json" };
import project from "../schemas/project.schema.json" with { type: "json" };
import renderPreset from "../schemas/render-preset.schema.json" with { type: "json" };
import session from "../schemas/session.schema.json" with { type: "json" };
import watchedFolder from "../schemas/watched-folder.schema.json" with { type: "json" };
import { ContractError } from "./errors.ts";
import type {
  AssetDerivedMedia,
  AssetFingerprints,
  AssetOverlap,
  ErrorInfo,
  Event,
  ExportManifest,
  ImportResult,
  Job,
  JobEvent,
  MediaAsset,
  Profile,
  Project,
  RenderPreset,
  Session,
  WatchedFolder,
} from "./generated/types.ts";
import { semanticIssues } from "./semantic.ts";
import { checkVersion } from "./versioning.ts";

/** Top-level contracts and their TypeScript types. */
export interface ContractTypes {
  "derived-media": AssetDerivedMedia;
  error: ErrorInfo;
  event: Event;
  "export-manifest": ExportManifest;
  fingerprint: AssetFingerprints;
  import: ImportResult;
  job: Job;
  "job-event": JobEvent;
  "media-asset": MediaAsset;
  overlap: AssetOverlap;
  profile: Profile;
  project: Project;
  "render-preset": RenderPreset;
  session: Session;
  "watched-folder": WatchedFolder;
}
export type ContractName = keyof ContractTypes;

/** Top-level contracts: name -> [schema, carries schema_version]. */
export const CONTRACTS: Record<ContractName, readonly [object, boolean]> = {
  "derived-media": [derivedMedia, true],
  error: [error, false],
  event: [event, true],
  "export-manifest": [exportManifest, true],
  fingerprint: [fingerprint, true],
  import: [importResult, true],
  job: [job, true],
  "job-event": [jobEvent, true],
  "media-asset": [mediaAsset, true],
  overlap: [overlap, true],
  profile: [profile, true],
  project: [project, true],
  "render-preset": [renderPreset, true],
  session: [session, true],
  "watched-folder": [watchedFolder, true],
};

const ajv = new Ajv2020({ allErrors: true, strict: true, allowUnionTypes: true });
ajv.addKeyword({ keyword: "tsType", schemaType: "string" }); // generator hint, no validation
// Register every schema before compiling any, so cross-file $refs (e.g. job -> error) resolve
// no matter which contract is loaded first. Mirrors the Python registry.
const SCHEMAS: { $id: string }[] = [
  common,
  evidence,
  ...Object.values(CONTRACTS).map(([s]) => s as { $id: string }),
];
for (const schema of SCHEMAS) ajv.addSchema(schema);
const validators = new Map<ContractName, ValidateFunction>();

function validator(contract: ContractName): ValidateFunction {
  let fn = validators.get(contract);
  if (!fn) {
    const id = (CONTRACTS[contract][0] as { $id: string }).$id;
    fn = ajv.getSchema(id);
    if (!fn) throw new Error(`schema ${id} is not registered`);
    validators.set(contract, fn);
  }
  return fn;
}

function issuePath(instancePath: string): string {
  if (!instancePath) return "(root)";
  return instancePath
    .slice(1)
    .split("/")
    .map((part) => part.replace(/~1/g, "/").replace(/~0/g, "~"))
    .reduce(
      (out, part) => (/^\d+$/.test(part) ? `${out}[${part}]` : out ? `${out}.${part}` : part),
      "",
    );
}

function describe(e: ErrorObject): string {
  return `${issuePath(e.instancePath)}: ${e.message ?? e.keyword}`;
}

/** Validate `document` against `contract` and return it typed. Throws ContractError. */
export function load<C extends ContractName>(contract: C, document: unknown): ContractTypes[C] {
  if (!(contract in CONTRACTS)) {
    throw new Error(`unknown contract '${String(contract)}'`);
  }
  if (CONTRACTS[contract][1]) checkVersion(contract, document);

  const validate = validator(contract);
  if (!validate(document)) {
    const issues = [...new Set((validate.errors ?? []).map(describe))].sort();
    throw new ContractError(contract, issues);
  }

  const issues = semanticIssues(contract, document);
  if (issues.length > 0) throw new ContractError(contract, issues);
  return document as ContractTypes[C];
}

/** Canonical JSON-compatible value (sorted keys). Equal to Python normalize() for the same input. */
export function normalize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(normalize);
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(
      Object.keys(value)
        .sort()
        .filter((k) => (value as Record<string, unknown>)[k] !== undefined)
        .map((k) => [k, normalize((value as Record<string, unknown>)[k])]),
    );
  }
  return value;
}
