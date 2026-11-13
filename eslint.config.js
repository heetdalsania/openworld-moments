// SPDX-License-Identifier: AGPL-3.0-or-later
import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  {
    ignores: [
      "**/dist/**",
      "output/**",
      "apps/desktop/src-tauri/bundle-input/**",
      ".playwright-cli/**",
      "**/target/**",
      "**/gen/**",
      "**/node_modules/**",
      "**/.venv/**",
      "services/**",
      "packages/contracts/src/generated/**",
      "packages/contracts/python/**",
    ],
  },
  js.configs.recommended,
  tseslint.configs.strict,
  {
    files: ["apps/desktop/src/**/*.{ts,tsx}"],
    languageOptions: { globals: globals.browser },
    plugins: { "react-hooks": reactHooks },
    rules: reactHooks.configs.recommended.rules,
  },
  {
    files: [
      "*.js",
      "apps/*/vite.config.ts",
      "packages/*/scripts/**/*.mjs",
      "packages/*/src/**/*.test.ts",
    ],
    languageOptions: { globals: globals.node },
  },
);
