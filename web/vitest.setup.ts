import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// The interface speaks the browser's language when nobody chose one: these
// tests read it in French, as LEKA's first users do (playwright.config.ts
// says the same of the browser tests). A test about languages says its own.
Object.defineProperty(window.navigator, "languages", { value: ["fr-FR", "fr"], configurable: true });
Object.defineProperty(window.navigator, "language", { value: "fr-FR", configurable: true });

// React Testing Library leaves the tree in the document. Without this, the
// second test in a file queries two sidebars and every "found more than one"
// failure looks like a bug in the component.
afterEach(cleanup);
