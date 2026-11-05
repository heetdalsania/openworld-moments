// SPDX-License-Identifier: Apache-2.0
// Fail if generated contract outputs differ from what is committed. Run after `pnpm contracts:generate`.
import { execFileSync } from "node:child_process";

const generated = [
  "packages/contracts/src/generated",
  "packages/contracts/python/openworld_moments_contracts/generated",
  "packages/contracts/python/openworld_moments_contracts/schemas",
];

// Only worktree changes and untracked files count: regeneration changed something that is not
// yet staged or committed. Staged-but-uncommitted output already matches the schemas.
const status = execFileSync("git", ["status", "--porcelain", "--", ...generated], {
  encoding: "utf8",
})
  .split("\n")
  .filter((line) => line.startsWith("??") || (line.length > 1 && line[1] !== " "))
  .join("\n");

// Ignored generated files would vanish from commits without any status line, so check separately.
const ignored = execFileSync(
  "git",
  ["ls-files", "--others", "--ignored", "--exclude-standard", "--", ...generated],
  { encoding: "utf8" },
)
  .split("\n")
  .filter((line) => line && !line.includes("__pycache__"));

if (ignored.length > 0) {
  console.error("Generated contract files are git-ignored and would not be committed:");
  console.error(ignored.join("\n"));
  process.exit(1);
}

if (status) {
  console.error("Generated contracts are out of date:\n" + status);
  console.error("\nRun `pnpm contracts:generate` and commit the result.");
  process.exit(1);
}
console.log("Generated contracts match the schemas.");
