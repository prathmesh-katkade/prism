/**
 * Monaco cannot run in jsdom (it needs a real browser canvas/DOM engine) - the same reason
 * query-studio.test.tsx already mocks "./query-editor" wholesale for its own test. This stub
 * only exists so Vite's module graph walk can resolve the "monaco-editor" specifier inside
 * query-editor.tsx's dynamic() factory when some other test (e.g. prism-shell.test.tsx) renders
 * the full shell without mocking that far down; the factory's `.then()` callback is never
 * exercised in jsdom, so the stub's shape doesn't need to match the real package.
 */
export {};
