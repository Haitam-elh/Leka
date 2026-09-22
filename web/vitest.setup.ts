import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// React Testing Library leaves the tree in the document. Without this, the
// second test in a file queries two sidebars and every "found more than one"
// failure looks like a bug in the component.
afterEach(cleanup);
