import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";
import path from "node:path";

const base = process.env.PRISM_PREVIEW_BASE_URL ?? "http://127.0.0.1:3201";
const output = path.resolve("docs/clean-pattern-review-v1/reference-comparisons");
mkdirSync(output, { recursive: true });
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1586, height: 992 }, colorScheme: "dark" });
async function captureVariants(name, keepNavScroll = false) {
  await page.evaluate((keepNavScroll) => {
    window.scrollTo(0, 0);
    for (const element of document.querySelectorAll(".workspace-content, .clean-issues, .clean-preview, .viz-fields, .viz-canvas, .sql-main-pane")) if (!keepNavScroll || !element.classList.contains("clean-issues")) element.scrollTop = 0;
  }, keepNavScroll);
  await page.screenshot({ path: path.join(output, `${name}-current-1586x992.png`) });
  await page.getByRole("button", { name: "Switch to light theme" }).click();
  await page.screenshot({ path: path.join(output, `${name}-light-1586x992.png`) });
  await page.setViewportSize({ width: 400, height: 844 });
  await page.screenshot({ path: path.join(output, `${name}-light-400x844.png`) });
  await page.getByRole("button", { name: "Switch to dark theme" }).click();
  await page.screenshot({ path: path.join(output, `${name}-dark-400x844.png`) });
  if (await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)) throw new Error(`${name} has document-level horizontal overflow at 400px`);
  await page.setViewportSize({ width: 1586, height: 992 });
}
const csv = [
  "customer_id,region,revenue,ordered_at",
  "C1001,Bangalore,1200,2026-01-12",
  "C1002,BENGALURU,1600,2026-01-14",
  "C1003,Bengaluru,1100,2026-01-16",
  "C1004,B'lore,1800,2026-01-18",
  "C1005,Mumbai,2000,2026-01-20",
  "C1006,Pune,1700,2026-01-22",
  "C1007,BLR-East,900,2026-01-24",
  "C1008,,1300,2026-01-26",
].join("\n") + "\n";
try {
  await page.goto(base);
  await page.getByRole("button", { name: /Overview native/i }).click();
  const [upload] = await Promise.all([
    page.waitForResponse((response) => response.url().endsWith("/api/v1/overview/datasets") && response.request().method() === "POST"),
    page.setInputFiles("#overview-upload", { name: "reference-customers.csv", mimeType: "text/csv", buffer: Buffer.from(csv) }),
  ]);
  if (!upload.ok()) throw new Error(`Upload ${upload.status()}: ${await upload.text()}`);
  const datasetId = (await upload.json()).dataset_id;
  for (const [name, button] of [["clean", /Clean native/i], ["sql-lab", /SQL Lab native/i], ["visualize", /Visualize native/i]]) {
    await page.getByRole("button", { name: button }).click();
    if (name === "clean") {
      await page.getByLabel("Data and transformation preview").waitFor();
      // Genuine multi-step recipe, built through the real draft flow (never a
      // fabricated "Applied" status or an invented recipe entry) - this is
      // what makes the numbered-step hierarchy in the capture below real
      // rather than decorative. Step 1: trim whitespace, added to the draft.
      await page.getByRole("button", { name: "+ Add step" }).click();
      await page.getByLabel("Operation", { exact: true }).selectOption("trim_whitespace");
      await page.getByLabel("Column", { exact: true }).fill("region");
      await page.locator(".clean-manual-form").getByRole("button", { name: "Preview", exact: true }).click();
      await page.getByRole("button", { name: "Add step to draft" }).waitFor();
      await page.getByRole("button", { name: "Add step to draft" }).click();
      await page.locator(".clean-recipe-draft").filter({ hasText: "DRAFT RECIPE" }).waitFor();
      // Step 2: the category-mapping review this file already exercised -
      // built the same real way and added as the draft's second step.
      await page.getByRole("button", { name: "+ Add step" }).click();
      await page.getByLabel("Operation", { exact: true }).selectOption("category_mapping");
      await page.getByLabel("Column", { exact: true }).fill("region");
      await page.locator(".clean-value-list").waitFor();
      for (const source of ["Bangalore", "BENGALURU", "B'lore", "BLR-East"]) {
        await page.locator(".clean-value-list li").filter({ has: page.locator("span").filter({ hasText: new RegExp(`^${source}$`) }) }).getByRole("checkbox").check();
      }
      await page.getByLabel("Map selected values to").fill("Bengaluru");
      await page.getByRole("button", { name: "Assign mapping" }).click();
      await page.locator(".clean-manual-form").getByRole("button", { name: "Preview", exact: true }).click();
      await page.locator(".clean-mapping-review").waitFor();
    }
    if (name === "sql-lab") {
      await page.locator(".monaco-editor").waitFor();
      await page.getByRole("button", { name: /Run query/ }).click();
      await page.getByText(/returned \/ .* rows/).waitFor();
    }
    if (name === "visualize") {
      // Each select's onChange closes over the spec state at render time. Firing
      // three selectOption() calls back to back, with no yield for React to
      // re-render and reattach a fresh handler between them, can let a later
      // change event read a stale pre-update spec and silently revert an
      // earlier one (observed: Mark reverting to the original suggestion after
      // Category/Aggregation fired immediately after it). A real user clicking
      // three separate dropdowns never fires this fast; waiting a tick between
      // each call here keeps the capture tool itself robust without touching
      // the product's own state handling.
      await page.getByLabel("Chart inspector").getByLabel("Mark").selectOption("horizontal_bar");
      await page.waitForTimeout(250);
      await page.getByLabel("Chart inspector").getByLabel("Category").selectOption("region");
      await page.waitForTimeout(250);
      await page.getByLabel("Chart inspector").getByLabel("Aggregation").selectOption("sum");
      await page.waitForTimeout(250);
      try { await page.getByRole("img", { name: /Horizontal bar chart/ }).waitFor({ timeout: 5000 }); }
      catch (error) { console.error(await page.locator(".viz-canvas").innerText()); await page.screenshot({ path: path.join(output, "visualize-debug.png") }); throw error; }
      // Exercise the reference's own Sort by / Currency controls so the
      // capture below shows real, interacted-with state, not just the
      // first-render default.
      await page.getByLabel("Chart inspector").getByLabel("Sort by").selectOption("value_desc");
      await page.waitForTimeout(250);
      await page.getByLabel("Chart inspector").getByLabel("Currency").selectOption("INR");
      await page.waitForTimeout(250);
      await page.getByRole("button", { name: /Inspect Bengaluru/ }).click();
      await page.getByText(/contributing row\(s\)/).waitFor();
    }
    await captureVariants(name);
  }
  await page.getByRole("button", { name: /Reports native/i }).click();
  await captureVariants("reports");
  await page.getByRole("button", { name: /Clean native/i }).click();
  await page.locator(".clean-issues .finding-list").last().locator("button").first().click();
  await page.locator(".clean-pattern-controls").scrollIntoViewIfNeeded();
  await captureVariants("pattern-review", true);
  console.log(JSON.stringify({ base, datasetId, output, viewport: "1586x992" }));
} finally {
  await browser.close();
}
