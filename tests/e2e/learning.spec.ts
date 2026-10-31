import { expect, test } from "@playwright/test";

// Failure traces could persist raw test cookies. Keep credential-bearing traces off.
test.use({ trace: "off" });

test("real learning journey preserves prediction, failed correction, guidance and committed note", async ({ page }, testInfo) => {
  test.setTimeout(90_000);
  const errors: string[] = [];
  // Guard fixture isolation without mocking a successful API response.
  await page.route("**/api/v1/**", (route) => {
    if (new URL(route.request().url()).origin !== "http://127.0.0.1:8000") return route.abort("blockedbyclient");
    return route.continue();
  });
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/learn/fastapi-payload-mismatch");
  await page.getByRole("button", { name: "Start lesson" }).click();
  await page.getByLabel("The request will be rejected", { exact: true }).check();
  const original = "I expect rejection because the sender and receiver use different field names.";
  await page.getByLabel("Why do you expect that?").fill(original);
  await page.getByRole("button", { name: "Lock prediction", exact: true }).click();
  const prediction = page.getByRole("region", { name: "Locked prediction" });
  await expect(prediction.getByText(original)).toBeVisible();
  await expect(page.getByRole("form", { name: "Initial prediction" })).toHaveCount(0);
  await page.getByLabel("Payload field").selectOption("body");
  await page.getByRole("button", { name: "Submit correction", exact: true }).click();
  await page.getByRole("button", { name: "Run verification", exact: true }).click();
  const failed = page.getByRole("region", { name: "Verification evidence, attempt 1" });
  await expect(failed.getByRole("heading", { name: "Request rejected" })).toBeVisible();
  await expect(failed.getByText("422", { exact: true })).toBeVisible();
  await expect(failed.getByText("0", { exact: true })).toBeVisible();
  await expect(failed.getByText('["missing:content", "extra_forbidden:body"]', { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Request a hint", exact: true }).click();
  await expect(page.getByText("Hint 1 · fixture guidance")).toBeVisible();
  await page.getByLabel("Payload field").selectOption("content");
  await page.getByRole("button", { name: "Submit correction", exact: true }).click();
  await page.getByRole("button", { name: "Run verification", exact: true }).click();
  const passed = page.getByRole("region", { name: "Verification evidence, attempt 2" });
  await expect(passed.getByRole("heading", { name: "Persistence verified" })).toBeVisible();
  await expect(passed.getByText("201", { exact: true })).toBeVisible();
  await expect(passed.getByText("1", { exact: true })).toBeVisible();
  await expect(passed.getByText(/Understanding request validation/).last()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Session complete", exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("region", { name: "Locked prediction" }).getByText(original)).toBeVisible();
  await expect(page.getByRole("heading", { name: "Attempt 1 · body", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Attempt 2 · content", exact: true })).toBeVisible();
  await expect(page.getByText("Hint 1 · fixture guidance")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Session complete", exact: true })).toBeVisible();
  await page.getByRole("region", { name: "Saved progress" }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: testInfo.outputPath("learning-complete.png"), fullPage: false });
  expect(errors).toEqual([]);
});
