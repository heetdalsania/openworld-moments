// SPDX-License-Identifier: Apache-2.0
// Single entry point for reading contract documents: version → schema → semantics.
// Mirrors validate.py.
import type { ErrorObject, ValidateFunction } from "ajv/dist/2020.js";
import modelManager from "../schemas/model-manager.schema.json" with { type: "json" };
import systemDoctor from "../schemas/system-doctor.schema.json" with { type: "json" };
import privacyReview from "../schemas/privacy-review.schema.json" with { type: "json" };
import editorProject from "../schemas/editor-project.schema.json" with { type: "json" };
import storyCandidate from "../schemas/story-candidate.schema.json" with { type: "json" };
import storyCandidates from "../schemas/story-candidates.schema.json" with { type: "json" };
import analysis from "../schemas/analysis.schema.json" with { type: "json" };
import evaluation from "../schemas/evaluation.schema.json" with { type: "json" };
import evaluationobservations from "../schemas/evaluation-observations.schema.json" with { type: "json" };
import evaluationreport from "../schemas/evaluation-report.schema.json" with { type: "json" };
import eventreview from "../schemas/event-review.schema.json" with { type: "json" };
import derivedMedia from "../schemas/derived-media.schema.json" with { type: "json" };
import error from "../schemas/error.schema.json" with { type: "json" };
import event from "../schemas/event.schema.json" with { type: "json" };
import exportManifest from "../schemas/export-manifest.schema.json" with { type: "json" };
import fingerprint from "../schemas/fingerprint.schema.json" with { type: "json" };
import importResult from "../schemas/import.schema.json" with { type: "json" };
import jobEvent from "../schemas/job-event.schema.json" with { type: "json" };
import job from "../schemas/job.schema.json" with { type: "json" };
import mediaAsset from "../schemas/media-asset.schema.json" with { type: "json" };
import overlap from "../schemas/overlap.schema.json" with { type: "json" };
import profilePatch from "../schemas/profile-patch.schema.json" with { type: "json" };
import profile from "../schemas/profile.schema.json" with { type: "json" };
import project from "../schemas/project.schema.json" with { type: "json" };
import renderPreset from "../schemas/render-preset.schema.json" with { type: "json" };
import session from "../schemas/session.schema.json" with { type: "json" };
import renderEncoders from "../schemas/render-encoders.schema.json" with { type: "json" };
import render from "../schemas/render.schema.json" with { type: "json" };
import collection from "../schemas/collection.schema.json" with { type: "json" };
import eventExport from "../schemas/event-export.schema.json" with { type: "json" };
import exportResult from "../schemas/export-result.schema.json" with { type: "json" };
import projectExport from "../schemas/project-export.schema.json" with { type: "json" };
import searchIndex from "../schemas/search-index.schema.json" with { type: "json" };
import search from "../schemas/search.schema.json" with { type: "json" };
import speechModels from "../schemas/speech-models.schema.json" with { type: "json" };
import transcript from "../schemas/transcript.schema.json" with { type: "json" };
import transcription from "../schemas/transcription.schema.json" with { type: "json" };
import watchedFolder from "../schemas/watched-folder.schema.json" with { type: "json" };
import compiledValidators from "./generated/validators.js";
import { ContractError } from "./errors.ts";
import type {
  PrivacyReview,
  ModelManager,
  SystemDoctor,
  EditorProject,
  StoryCandidate,
  StoryCandidates,
  EvaluationManifest,
  EvaluationObservations,
  EvaluationReport,
  EventReview,
  AnalysisResult,
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
  ProfilePatch,
  Project,
  RenderPreset,
  Collection,
  EventExportLine,
  ExportResult,
  ProjectExport,
  SearchResults,
  SearchIndexStatus,
  Session,
  RenderEncoders,
  RenderRecord,
  SpeechModels,
  Transcript,
  TranscriptionResult,
  WatchedFolder,
} from "./generated/types.ts";
import { semanticIssues } from "./semantic.ts";
import { checkVersion } from "./versioning.ts";

/** Top-level contracts and their TypeScript types. */
export interface ContractTypes {
  "model-manager": ModelManager;
  "system-doctor": SystemDoctor;
  "privacy-review": PrivacyReview;
  "editor-project": EditorProject;
  "story-candidate": StoryCandidate;
  "story-candidates": StoryCandidates;
  "event-review": EventReview;
  "evaluation-report": EvaluationReport;
  "evaluation-observations": EvaluationObservations;
  evaluation: EvaluationManifest;
  analysis: AnalysisResult;
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
  "profile-patch": ProfilePatch;
  project: Project;
  "render-preset": RenderPreset;
  session: Session;
  render: RenderRecord;
  "render-encoders": RenderEncoders;
  collection: Collection;
  "event-export": EventExportLine;
  "export-result": ExportResult;
  "project-export": ProjectExport;
  search: SearchResults;
  "search-index": SearchIndexStatus;
  "speech-models": SpeechModels;
  transcript: Transcript;
  transcription: TranscriptionResult;
  "watched-folder": WatchedFolder;
}
export type ContractName = keyof ContractTypes;

/** Top-level contracts: name -> [schema, carries schema_version]. */
export const CONTRACTS: Record<ContractName, readonly [object, boolean]> = {
  "model-manager": [modelManager, true],
  "system-doctor": [systemDoctor, true],
  "privacy-review": [privacyReview, true],
  "editor-project": [editorProject, true],
  "story-candidate": [storyCandidate, true],
  "story-candidates": [storyCandidates, true],
  evaluation: [evaluation, true],
  "evaluation-observations": [evaluationobservations, true],
  "evaluation-report": [evaluationreport, true],
  "event-review": [eventreview, true],
  analysis: [analysis, true],
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
  "profile-patch": [profilePatch, true],
  project: [project, true],
  "render-preset": [renderPreset, true],
  session: [session, true],
  render: [render, true],
  "render-encoders": [renderEncoders, true],
  collection: [collection, true],
  "event-export": [eventExport, true],
  "export-result": [exportResult, true],
  "project-export": [projectExport, true],
  search: [search, true],
  "search-index": [searchIndex, true],
  "speech-models": [speechModels, true],
  transcript: [transcript, true],
  transcription: [transcription, true],
  "watched-folder": [watchedFolder, true],
};

function validator(contract: ContractName): ValidateFunction {
  const id = (CONTRACTS[contract][0] as { $id: string }).$id;
  const fn = compiledValidators[id];
  if (!fn) throw new Error(`schema ${id} is not registered`);
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
