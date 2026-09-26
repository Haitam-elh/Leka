import { dirname } from "path";
import { fileURLToPath } from "url";
import { FlatCompat } from "@eslint/eslintrc";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const compat = new FlatCompat({
  baseDirectory: __dirname,
});

const eslintConfig = [
  ...compat.extends("next/core-web-vitals", "next/typescript"),
  {
    ignores: [
      "node_modules/**",
      ".next/**",
      "out/**",
      "build/**",
      "next-env.d.ts",
      // leka-core.com's own pages and scripts, served as they are: plain
      // browser JavaScript, not this app's TypeScript, reviewed in their
      // pull requests (docs/deployment.md, "Changing the site").
      "public/**",
    ],
  },
];

export default eslintConfig;
