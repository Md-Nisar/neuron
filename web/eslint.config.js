import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "coverage"] },
  js.configs.recommended,
  ...tseslint.configs.strictTypeChecked,
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      globals: globals.browser,
      parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname },
    },
    plugins: { "react-hooks": reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // The app renders model text; never let a lint-clean change reach for raw HTML.
      "no-restricted-syntax": [
        "error",
        {
          selector: "JSXAttribute[name.name='dangerouslySetInnerHTML']",
          message: "Model, tool and title text is untrusted (ADR 0010, decision 7).",
        },
      ],
    },
  },
  { files: ["**/*.js"], ...tseslint.configs.disableTypeChecked },
  { files: ["eslint.config.js", "vite.config.ts"], languageOptions: { globals: globals.node } },
);
