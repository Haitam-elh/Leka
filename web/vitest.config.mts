import path from "node:path";

import { defineConfig } from "vitest/config";

/**
 * Component tests, in a fake browser.
 *
  * No @vitejs/plugin-react: it wants Babel 8 and `shadcn` pins Babel 7, so
 * installing it means forcing a resolution npm itself calls potentially
 * broken. esbuild transforms the JSX instead, which is all a test run needs
 * — the plugin's reason to exist is Fast Refresh in the dev server.
 *
 * e2e/ is excluded: those are Playwright's, and they need a real browser and
 * a running API.
 */
export default defineConfig({
  resolve: {
    alias: { "@": path.resolve(import.meta.dirname, ".") },
  },
  // Next sets `jsx: "preserve"` in tsconfig.json — right for Next, and it
  // leaves Vite unable to parse a component file. Vite 8 transforms with
  // Oxc, so this is where the override goes; in tsconfig.json it would
  // change how Next itself compiles the application.
  oxc: { jsx: { runtime: "automatic", importSource: "react" } },
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    include: ["**/*.test.{ts,tsx}"],
    exclude: ["node_modules/**", ".next/**", "e2e/**"],
  },
});
