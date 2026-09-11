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

// A <div>/<span> with onClick is only flagged when its opening tag lacks all of: an explicit
// ARIA role + tabIndex (a deliberately built custom interactive control, e.g. role="tab" for a
// roving-tabindex widget), or aria-hidden="true" (a pointer-only affordance intentionally kept
// out of the accessibility tree, e.g. a redundant close "x" alongside a keyboard shortcut).
const OPENING_TAG = /<(div|span)\b[^>]*>/g;

for (const path of await files(sourceRoot)) {
  if (!path.endsWith(".tsx")) continue;
  const source = await readFile(path, "utf8");
  for (const [tag] of source.matchAll(OPENING_TAG)) {
    if (!/\bonClick=/.test(tag)) continue;
    const isCustomWidget = /\brole=/.test(tag) && /\btabIndex=/.test(tag);
    const isHiddenFromA11yTree = /\baria-hidden="true"/.test(tag);
    if (!isCustomWidget && !isHiddenFromA11yTree) {
      errors.push(`${path}: non-semantic click target`);
      break;
    }
  }
  if (/<img(?![^>]*\balt=)/.test(source)) errors.push(`${path}: image without alt text`);
}

if (errors.length) {
  console.error(errors.join("\n"));
  process.exitCode = 1;
} else {
  console.log("Accessibility baseline: passed");
}
