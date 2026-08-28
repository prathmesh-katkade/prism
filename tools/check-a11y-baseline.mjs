import { readdir, readFile } from "node:fs/promises";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const sourceRoot = fileURLToPath(new URL("../apps/web/src/", import.meta.url));
const errors = [];

async function files(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  return (await Promise.all(entries.map(async (entry) => {
    const path = join(directory, entry.name);
    return entry.isDirectory() ? files(path) : [path];
  }))).flat();
}

for (const path of await files(sourceRoot)) {
  if (!path.endsWith(".tsx")) continue;
  const source = await readFile(path, "utf8");
  if (/<(div|span)[^>]+onClick=/.test(source)) errors.push(`${path}: non-semantic click target`);
  if (/<img(?![^>]*\balt=)/.test(source)) errors.push(`${path}: image without alt text`);
}

if (errors.length) {
  console.error(errors.join("\n"));
  process.exitCode = 1;
} else {
  console.log("Accessibility baseline: passed");
}
