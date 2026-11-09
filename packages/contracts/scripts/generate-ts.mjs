// SPDX-License-Identifier: Apache-2.0
// Generate TypeScript types from ../schemas into src/generated/types.ts.
// Deterministic: one bundled file, sorted inputs, no timestamps, no network.
import { readdir, readFile, writeFile, mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { compile } from "json-schema-to-typescript";
import { Ajv2020 } from "ajv/dist/2020.js";
import standaloneCode from "ajv/dist/standalone/index.js";

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

// Compile validation while building, so browser imports never need unsafe-eval.
const ajv = new Ajv2020({
  allErrors: true,
  strict: true,
  allowUnionTypes: true,
  code: { source: true, esm: true, lines: true },
});
ajv.addKeyword({ keyword: "tsType", schemaType: "string" });
const schemas = await Promise.all(
  files.map(async (file) => JSON.parse(await readFile(path.join(schemaDir, file), "utf8"))),
);
for (const schema of schemas) ajv.addSchema(schema);
const exports = Object.fromEntries(schemas.map((schema, i) => [`contractValidator${i}`, schema.$id]));
let validation = standaloneCode(ajv, exports);
// Ajv emits CommonJS references to small runtime helpers even in ESM mode.
// Use static imports and normalize Node/bundler CJS interop without evaluation.
const helpers = new Map();
validation = validation.replace(
  /require\("(ajv\/dist\/runtime\/[a-zA-Z0-9_-]+)"\)\.default/g,
  (_match, module) => {
    if (!helpers.has(module)) helpers.set(module, `runtime${helpers.size}`);
    return helpers.get(module);
  },
);
if (/\brequire\s*\(/.test(validation)) throw new Error("Unexpected standalone runtime dependency");
const imports = [...helpers]
  .map(
    ([module, name]) =>
      `import ${name}Module from "${module}.js";\nconst ${name} = typeof ${name}Module === "function" ? ${name}Module : ${name}Module.default;`,
  )
  .join("\n");
const registry = Object.entries(exports)
  .map(([name, id]) => `${JSON.stringify(id)}: ${name}`)
  .join(",\n");
await writeFile(
  path.join(root, "src/generated/validators.js"),
  `${banner}\n${imports}\n${validation}\nexport default {${registry}};\n`,
);
await writeFile(
  path.join(root, "src/generated/validators.d.ts"),
  `${banner}\nimport type { ValidateFunction } from "ajv";\ndeclare const validators: Record<string, ValidateFunction>;\nexport default validators;\n`,
);
console.log(`Generated CSP-safe standalone validators for ${schemas.length} schemas`);
