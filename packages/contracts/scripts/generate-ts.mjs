// SPDX-License-Identifier: Apache-2.0
// Generate TypeScript types from ../schemas into src/generated/types.ts.
// Deterministic: one bundled file, sorted inputs, no timestamps, no network.
import { readdir, readFile, writeFile, mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { compile } from "json-schema-to-typescript";

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const schemaDir = path.join(root, "schemas");
const outFile = path.join(root, "src", "generated", "types.ts");
const ID_BASE = "https://github.com/heetdalsania/openworld-moments/contracts/";

const files = (await readdir(schemaDir)).filter((f) => f.endsWith(".schema.json")).sort();

// Resolve schema $ids to local files so generation never touches the network.
const localResolver = {
  order: 1,
  canRead: (file) => file.url.startsWith(ID_BASE) || file.url.startsWith(schemaDir),
  read: async (file) => {
    const name = path.basename(file.url.split("#")[0]);
    return readFile(path.join(schemaDir, name), "utf8");
  },
};

// A synthetic root that references every schema keeps shared types declared once.
const bundle = {
  title: "ContractsBundle",
  type: "object",
  additionalProperties: false,
  properties: Object.fromEntries(
    files
      .filter((f) => f !== "common.schema.json")
      .map((f) => [f.replace(".schema.json", ""), { $ref: `${ID_BASE}${f}` }]),
  ),
};

// Split so license scanners do not read this string as this script's own header.
const spdx = "SPDX-License-" + "Identifier";
const banner = [
  `// ${spdx}: Apache-2.0`,
  "// GENERATED FILE. Do not edit by hand.",
  "// Source: packages/contracts/schemas/*.schema.json",
  "// Regenerate with: pnpm contracts:generate",
].join("\n");

const ts = await compile(bundle, "ContractsBundle", {
  bannerComment: banner,
  cwd: schemaDir,
  additionalProperties: false,
  unreachableDefinitions: true,
  strictIndexSignatures: true,
  format: true,
  style: { printWidth: 100 },
  $refOptions: { resolve: { local: localResolver, http: false, file: localResolver } },
});

await mkdir(path.dirname(outFile), { recursive: true });
await writeFile(outFile, ts);
console.log(`Generated ${path.relative(root, outFile)} from ${files.length} schemas`);
