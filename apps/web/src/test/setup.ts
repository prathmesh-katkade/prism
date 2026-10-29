import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => cleanup());

// jsdom has no ResizeObserver - real browsers (and the packaged desktop
// app's real webview) do. This is a test-environment gap, not something to
// work around in production code: a no-op stub lets layout code that
// observes real elements (e.g. prism-shell.tsx's footer-alignment
// measurement) run under jsdom without crashing, the same way real browsers
// just deliver no resize callbacks for elements that never actually resize.
if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}
