import { expect, test } from "@playwright/test";

test("History workspace shows a real SQL Lab result through the live API and opens its evidence", async ({ page, request }) => {
  const upload = await request.post("http://127.0.0.1:8000/api/v1/overview/datasets", {
    multipart: {
      file: {
        name: "history-live.csv",
        mimeType: "text/csv",
        buffer: Buffer.from("id,revenue,segment\n1,10,North\n2,12,South\n3,14,North\n")
      }
    }
  });
  expect(upload.status()).toBe(201);
  const dataset = await upload.json() as { dataset_id: string };

  await page.goto("/");
  await page.getByRole("button", { name: /SQL Lab native/i }).click();
  await expect(page.locator(".monaco-editor")).toBeVisible();

  // The live suite shares one API process, so earlier tests may have created
  // other local datasets. Bind SQL Lab to the dataset created by THIS test
  // instead of relying on connection-list ordering. Use the toolbar's actual
  // select rather than its accessible label because Monaco/query hydration can
  // render before the labelled control is exposed to the accessibility tree.
  const source = page.locator(".query-toolbar select");
  await expect(source).toBeVisible({ timeout: 10_000 });
  const targetConnectionId = `local:${dataset.dataset_id}`;
  await expect(source.locator(`option[value="${targetConnectionId}"]`)).toHaveCount(1, { timeout: 10_000 });

  // In the common case the newly uploaded dataset is already the selected
  // connection and its schema request has completed before this assertion. Do
  // not wait for a second response that will never arrive. Only synchronize on
  // the schema request when we actually change the connection.
  if (await source.inputValue() !== targetConnectionId) {
    const schemaResponse = page.waitForResponse((response) => {
      const decodedUrl = decodeURIComponent(response.url());
      return decodedUrl.includes(`/sql-lab/connections/${targetConnectionId}/schema`) && response.status() === 200;
    });
    await source.selectOption(targetConnectionId);
    await schemaResponse;
  }

  const runQuery = page.getByRole("button", { name: /Run query/ });
  await expect(runQuery).toBeEnabled();
  // Sync on the actual results response rather than a bare click - see
  // sql-lab-live.spec.ts for why.
  const [resultsResponse] = await Promise.all([
    page.waitForResponse((response) => /\/sql-lab\/runs\/[^/]+\/results/.test(response.url()) && response.status() === 200),
    runQuery.click(),
  ]);
  expect(resultsResponse.ok()).toBe(true);
  await expect(page.getByText("3 returned / 3 total rows")).toBeVisible({ timeout: 15_000 });

  // Recording a SQL run durably is what makes it show up in History - this is
  // the same registration path every native workflow's "Inspect result" /
  // "Use as AI evidence" action uses.
  await page.getByRole("button", { name: "Inspect result" }).click();

  await page.getByRole("button", { name: /History native/i }).click();
  await expect(page.getByRole("heading", { name: "Analytical history" })).toBeVisible();
  await page.getByLabel("Search analytical history").fill("query_result");
  const row = page.locator("tbody tr", { hasText: "query result" }).first();
  await expect(row).toBeVisible({ timeout: 10_000 });
  await expect(row.getByText(/current|stale/)).toBeVisible();

  await row.getByRole("button", { name: "Inspect" }).click();
  const inspector = page.getByRole("complementary", { name: "Evidence inspector" });
  await expect(inspector.getByRole("heading", { name: "SQL result" })).toBeVisible({ timeout: 10_000 });
});
