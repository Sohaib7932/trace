import { expect, test } from "@playwright/test";

test("homepage preserves prediction locking and labels sample results honestly", async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("understand");
  await page.screenshot({ path: testInfo.outputPath("homepage.png"), fullPage: false });
  const demo = page.locator("#demo");
  const lock = demo.getByRole("button", { name: "Lock prediction" });
  await expect(lock).toBeDisabled();
  await demo.getByText("Note saved", { exact: true }).click();
  await expect(demo.getByRole("radio").first()).toBeChecked();
  await lock.click();
  await expect(demo.getByText("Your prediction", { exact: true })).toBeVisible();
  await expect(demo.getByRole("radio")).toHaveCount(0);
  await demo.getByRole("button", { name: "Show sample result" }).click();
  await expect(demo.getByText("Prediction differed", { exact: true })).toBeVisible();
  await expect(demo.getByText("Demonstration. Responses and the contents of notes here", { exact: false })).toBeVisible();
  await expect(demo.getByRole("button", { name: "Try a change" })).toBeVisible();
  expect(errors).toEqual([]);
});
