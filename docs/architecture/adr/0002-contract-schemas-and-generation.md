# ADR-0002: JSON Schema 2020-12 contracts with generated TypeScript and Pydantic types

- Status: Accepted
- Date: 2026-11-05
- Milestone: M01
- Deciders: project maintainers

## Context

The UI (TypeScript), host (Rust), and worker (Python) must agree on IDs, time
conventions, events, jobs, profiles, projects, presets, and export manifests
(spec §8.4, §8.9.3, §9.4–9.5, §11.1). ADR-0001 requires these contracts to be
versioned so either side can change independently. Types written by hand in
each language drift.

## Decision

- **Source of truth:** JSON Schema **draft 2020-12** files in
  `packages/contracts/schemas/`, licensed Apache-2.0. One file per contract;
  shared primitives in `common.schema.json`. Every schema has a stable `$id`
  under `https://github.com/heetdalsania/openworld-moments/contracts/`. The IDs
  are names, not URLs to fetch: all tools resolve them locally.
- **TypeScript types:** `json-schema-to-typescript`, bundled into one file
  (`src/generated/types.ts`) so shared types are declared once.
- **TypeScript validation:** Ajv (`ajv/dist/2020`) in strict mode.
- **Python models:** `datamodel-code-generator` → Pydantic v2 (`generated/`), with
  root models collapsed and enums emitted as `Literal` to match the TypeScript
  string unions.
- **Python validation:** `jsonschema` (Draft 2020-12) with a local
  `referencing` registry.
- **Semantic rules** that JSON Schema cannot express (region inside the frame,
  end ≥ start, failed jobs carry an error, ...) are implemented in both
  languages and held equal by the shared fixture suite.
- **Determinism:** generation never uses the network, writes no timestamps,
  and formats its own output. CI regenerates and fails on any diff.
- **Rust:** not generated in M01. The host gets types when it first needs them
  (M03), from the same schemas.

## Consequences

- One edit to a schema updates both languages; drift is caught in CI.
- Each language still has a small hand-written layer (versioning, semantics,
  `load()`), which the fixtures keep aligned.
- `json-schema-to-typescript` does not understand 2020-12 `prefixItems`, so
  tuple types carry a `tsType` hint. Ajv is told to ignore that keyword.
- Schemas are vendored into the Python package so it validates without the
  repository checkout; the drift check covers the copies.

## Alternatives considered

- **Pydantic models as source, exported to JSON Schema:** Python-centric, and
  the UI would depend on a Python step for its types.
- **TypeBox/Zod as source:** TypeScript-centric, same problem in reverse.
- **Protocol Buffers:** strong tooling but poor fit for human-edited project
  and profile files.
- **OpenAPI:** describes endpoints, which are out of scope until M03; its
  schema dialect lags 2020-12 in some tools.
