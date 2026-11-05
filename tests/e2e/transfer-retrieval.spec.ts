import { expect, test, type Page } from "@playwright/test";
import { signUp } from "./helpers/account";
import { mkdir, rename, rm, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { setTimeout as delay } from "node:timers/promises";

test.use({ trace: "off" });
const clockPath = resolve("test-results/e2e-clock.json");
// Back to real time afterwards, so signed-in tokens in later tests are not judged by this clock.
test.afterEach(() => rm(clockPath, { force: true }));
async function setClock(now: string) {
  await mkdir(dirname(clockPath), { recursive: true });
  await writeFile(`${clockPath}.tmp`, JSON.stringify({ now }), "utf8");
  for (let attempt = 0; ; attempt++) {
    try { await rename(`${clockPath}.tmp`, clockPath); break; }
    catch (error) {
      if (attempt >= 10 || !["EPERM", "EBUSY"].includes((error as NodeJS.ErrnoException).code ?? "")) throw error;
      // Windows can briefly lock the old file during the test server's atomic read.
      await delay(25);
    }
  }
}
async function lockPrediction(page: Page, reasoning: string) {
  await page.locator("label", { hasText: /The request will be rejected/ }).click();
  await page.getByLabel("Why do you expect that?").fill(reasoning);
  await page.getByRole("button", { name: "Lock prediction", exact: true }).click();
  await expect(page.getByRole("region", { name: "Locked prediction" }).getByText(reasoning)).toBeVisible();
}

test("original completion unlocks real transfer and persisted timed retrieval", async ({ page, request }, testInfo) => {
  test.setTimeout(210_000);
  await signUp(page, request);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/api/v1/**", (route) => new URL(route.request().url()).origin === "http://127.0.0.1:8000" ? route.continue() : route.abort("blockedbyclient"));
  await setClock("2026-11-01T09:00:00Z");
  await page.goto("/learn/fastapi-nested-payload-transfer");
  await expect(page.getByText(/Complete the original lesson to unlock/)).toBeVisible();
  await page.goto("/learn/fastapi-payload-mismatch");
  await lockPrediction(page, "The outgoing key differs from the receiver.");
  await page.getByRole("button", { name: /^Change field name, currently / }).click();
  await page.getByRole("option", { name: /"content"/ }).click();
  await page.getByRole("button", { name: "Check my change", exact: true }).click();
  await expect(page.getByText(/Verified (on first try|after a revision)/)).toBeVisible();
  await page.goto("/learn/fastapi-nested-payload-transfer");
  await expect(page.getByRole("heading", { name: "The Nested Payload Problem", exact: true })).toBeVisible();
  const original = "The priority value is present, but the receiving model requires a nested object.";
  await lockPrediction(page, original);
  await expect(page.getByRole("button", { name: /Nest this field/ })).toBeDisabled();
  await page.getByRole("button", { name: "Run the original request", exact: true }).click();
  const failed = page.getByRole("region", { name: "Verification evidence, attempt 1" });
  await expect(failed.getByText("422", { exact: true })).toBeVisible();
  await expect(failed.getByText("0", { exact: true })).toBeVisible();
  await expect(failed.getByText('["missing:metadata", "extra_forbidden:priority"]', { exact: true })).toBeVisible();
  await page.getByRole("button", { name: /Nest this field/ }).click();
  await expect(page.getByRole("button", { name: /Undo nesting/ })).toBeVisible();
  await page.getByRole("button", { name: "Check my change", exact: true }).click();
  const passed = page.getByRole("region", { name: "Verification evidence, attempt 2" });
  await expect(passed.getByText("201", { exact: true })).toBeVisible();
  await expect(passed.getByText("1", { exact: true })).toBeVisible();
  await expect(passed.getByText(/Prepare the product demo/).last()).toBeVisible();
  await expect(passed.getByText(/"priority": "high"/).last()).toBeVisible();
  await page.reload();
  await expect(page.getByRole("region", { name: "Locked prediction" }).getByText(original)).toBeVisible();
  await expect(page.getByRole("heading", { name: /Your change · attempt 1/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: /Your change · attempt 2/ })).toBeVisible();

  // Follow-ups come from the server's clock and are answered on the account page.
  await setClock("2026-11-02T08:59:59.999999Z");
  await page.goto("/account");
  await expect(page.getByRole("heading", { name: "Your numbers" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "A follow-up is ready" })).toHaveCount(0);
  await setClock("2026-11-02T09:00:00Z");
  await page.goto("/account");
  await expect(page.getByRole("heading", { name: "A follow-up is ready" })).toBeVisible();
  const first = page.locator("li", { hasText: "Follow-up 1" });
  await expect(first).toContainText("Due now");
  await first.getByRole("button", { name: "Answer now" }).click();
  await expect(first.getByText("Recall the shipment contract", { exact: true })).toBeVisible();
  await expect(first.getByText(/Values and structure both matter/)).toHaveCount(0);
  await first.getByLabel("Any request containing zone must be accepted.").check();
  await first.getByRole("button", { name: "Save my answer" }).click();
  await expect(first.getByText("Answer 1 · Not quite")).toBeVisible();
  await first.getByLabel("The zone value is at a different JSON level than the schema expects.").check();
  await first.getByRole("button", { name: "Save my answer" }).click();
  // A completed follow-up leaves the Overview; the next one appears once the server says it is due.
  await expect(page.getByRole("heading", { name: "A follow-up is ready" })).toHaveCount(0);
  await setClock("2026-11-09T09:00:00Z");
  await page.goto("/account");
  const second = page.locator("li", { hasText: "Follow-up 2" });
  await expect(second).toContainText("Due now");
  await second.getByRole("button", { name: "Answer now" }).click();
  await second.getByLabel("Place format inside an output object and retain name at the root.").check();
  await second.getByRole("button", { name: "Save my answer" }).click();
  await expect(page.getByRole("heading", { name: "A follow-up is ready" })).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath("retrieval-complete.png"), fullPage: false });
  expect(errors).toEqual([]);
});
