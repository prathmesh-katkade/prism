import { expect, test } from "@playwright/test";

const api = process.env.NEXT_PUBLIC_PRISM_API_URL ?? "http://127.0.0.1:8000";

test("Atlas date clarification uses a real Clean re-preview and leaves Apply to the analyst", async ({ page, request }) => {
  const upload = await request.post(`${api}/api/v1/overview/datasets`, { multipart: { file: {
    name: "ambiguous-orders.csv", mimeType: "text/csv",
    buffer: Buffer.from("segment,ordered_at\nNorth,03/04/2026\nSouth,15/06/2026\nWest,not-a-date\n"),
  } } });
  expect(upload.ok()).toBe(true);
  const datasetId = (await upload.json() as { dataset_id: string }).dataset_id;

  await page.route("**/api/v1/workspace-proposals", async (route) => {
    const body = route.request().postDataJSON() as { kind: string; dataset_id: string; expected_revision: number };
    expect(body).toMatchObject({ kind: "clean", dataset_id: datasetId, expected_revision: 0 });
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      kind: "clean", provider: "ollama", explanation: "Choose the intended date order before conversion.", evidence: [],
      clean_operation: { operation: "convert_type", column: "ordered_at", target_type: "datetime" },
      clarification: { question: "Is 03/04/2026 day first or month first?", column: "ordered_at", choices: [
        { label: "Day first", parameters: { date_format: "%d/%m/%Y" } },
        { label: "Month first", parameters: { date_format: "%m/%d/%Y" } },
      ] },
    }) });
  });

  await page.goto(`/?dataset_id=${encodeURIComponent(datasetId)}`);
  await page.getByRole("button", { name: /Clean native/i }).click();
  await page.locator(".clean-dataset-header .atlas-launcher").click();
  await page.getByRole("textbox", { name: "Ask Atlas" }).fill("Convert ordered_at to dates");
  await page.getByRole("button", { name: "Ask Atlas", exact: true }).click();
  await expect(page.getByText("Is 03/04/2026 day first or month first?")).toBeVisible();
  await expect(page.getByRole("button", { name: "Review in Step settings" })).toHaveCount(0);

  const [resumed] = await Promise.all([
    page.waitForResponse((response) => response.url().endsWith(`/api/v1/clean/datasets/${datasetId}/preview`) && response.request().method() === "POST"),
    page.getByRole("button", { name: "Day first", exact: true }).click(),
  ]);
  expect(resumed.ok()).toBe(true);
  expect(resumed.request().postDataJSON()).toMatchObject({ operation: "convert_type", column: "ordered_at", target_type: "datetime", date_format: "%d/%m/%Y" });
  await expect(page.getByText(/Previewed with Day first/)).toBeVisible();
  expect((await request.get(`${api}/api/v1/overview/datasets/${datasetId}/profile`)).ok()).toBe(true);
  const profile = await (await request.get(`${api}/api/v1/overview/datasets/${datasetId}/profile`)).json() as { dataset: { revision: number } };
  expect(profile.dataset.revision).toBe(0);

  await page.getByRole("button", { name: "Review in Step settings" }).click();
  await expect(page.getByLabel("Date format")).toHaveValue("%d/%m/%Y");
  await expect(page.getByRole("button", { name: "Apply reviewed change" })).toBeVisible();
  expect((await (await request.get(`${api}/api/v1/overview/datasets/${datasetId}/profile`)).json() as { dataset: { revision: number } }).dataset.revision).toBe(0);
});
