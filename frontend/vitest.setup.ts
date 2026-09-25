import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// jsdom persists the document between tests in the same file, so a component left
// mounted by one test is still in the tree when the next one queries it -- which makes
// `getByText` find the previous test's element and pass for the wrong reason.
afterEach(() => {
  cleanup();
});
