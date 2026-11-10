// SPDX-License-Identifier: Apache-2.0
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { expect, it } from "vitest";

it("validates fixtures when runtime string code generation is forbidden", () => {
  const result = execFileSync(
    process.execPath,
    [
      "--disallow-code-generation-from-strings",
      "--input-type=module",
      "-e",
      `import { readdirSync, readFileSync, existsSync } from 'node:fs';
       import { CONTRACTS, load } from './src/index.ts';
       let checked = 0;
       for (const contract of Object.keys(CONTRACTS)) {
         for (const kind of ['valid', 'invalid']) {
           const directory = 'fixtures/' + contract + '/' + kind;
           if (!existsSync(directory)) continue;
           for (const file of readdirSync(directory).filter(name => name.endsWith('.json'))) {
             const document = JSON.parse(readFileSync(directory + '/' + file, 'utf8'));
             let rejected = false;
             try { load(contract, document); } catch { rejected = true; }
             if (rejected !== (kind === 'invalid')) throw Error(contract + '/' + kind + '/' + file);
             checked++;
           }
         }
       }
       if (checked < 100) throw Error('Missing contract fixtures');
       console.log('CSP-safe fixtures: ' + checked);`,
    ],
    { cwd: fileURLToPath(new URL("..", import.meta.url)), encoding: "utf8", timeout: 15000 },
  );
  expect(result).toMatch(/CSP-safe fixtures: \d+/);
});
