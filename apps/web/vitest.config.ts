import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
  root: __dirname,
  resolve: {
    // Monaco cannot run in jsdom and its package.json confuses Vite's resolver when Vite walks
    // the module graph of any test that transitively imports query-editor.tsx without mocking
    // it (see the stub file for why this is safe). Real Monaco behavior is covered by Playwright.
    alias: { "monaco-editor": fileURLToPath(new URL("./src/test/monaco-editor-stub.ts", import.meta.url)) }
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.tsx"]
  }
});
