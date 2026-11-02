import { expect, test, type Page, type APIRequestContext } from "@playwright/test";

const API = "http://127.0.0.1:8100";

async function signUp(page: Page, request: APIRequestContext) {
  const email = `ai-flow-${crypto.randomUUID()}@example.test`;
  await page.goto("/sign-up");
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password", { exact: true }).fill("Controlled-browser-fixture-47");
  await page.getByLabel("Confirm password", { exact: true }).fill("Controlled-browser-fixture-47");
  await page.getByRole("button", { name: "Create account", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Check your inbox" })).toBeVisible();
  const mail = await request.get(`http://127.0.0.1:8101/fixture/mail?email=${encodeURIComponent(email)}`);
  await page.goto((await mail.json()).link);
  await expect(page).toHaveURL(/\/account$/);
}

test.beforeEach(async ({ page, request }) => {
  await request.post(`${API}/__fixture__/ai-outcome/normal`);
  await page.route(/^https?:\/\/(?!127\.0\.0\.1)/, (route) => route.abort("blockedbyclient"));
});

test("real frontend adapter reaches owned tutor and sourced support APIs; fixtures stay labelled", async ({ page, request }) => {
  test.setTimeout(120_000);
  await signUp(page, request);
  await page.goto("/learn/fastapi-payload-mismatch");
  await page.getByRole("button", { name: "Start lesson", exact: true }).click();
  await expect(page.getByLabel("The request will be rejected", { exact: true })).toBeVisible();
  if (await page.locator(".tutor-bar").isVisible()) await page.locator(".tutor-bar button").click();
  const tutor = page.getByRole("dialog", { name: "Lesson tutor", exact: true });
  const panel = await tutor.isVisible() ? tutor : page.getByRole("complementary", { name: "Lesson tutor", exact: true });
  const response = page.waitForResponse((r) => r.url().endsWith("/tutor/ask") && r.request().method() === "POST");
  await panel.getByRole("button", { name: "Explain this concept", exact: true }).click();
  const result = await response;
  expect(result.status()).toBe(200);
  expect(result.headers()["cache-control"]).toBe("no-store");
  expect(Object.keys(result.request().postDataJSON())).toEqual(["question"]);
  await expect(panel.locator(".tutor-reply")).toContainText("Test fixture guidance");
  await expect(panel.locator(".tutor-reply")).toContainText("With extra='forbid'");
  await expect(panel.getByRole("button", { name: "Demo responses" })).toHaveCount(0);
  if (await tutor.isVisible()) await tutor.getByRole("button", { name: "Close lesson tutor" }).click();
  await page.getByRole("button", { name: "Help", exact: true }).click();
  const help = page.getByRole("dialog", { name: "Trace Help" });
  const supportResponse = page.waitForResponse((r) => r.url().endsWith("/support/ask") && r.request().method() === "POST");
  await help.getByLabel("Your question").fill("When are review checkpoints due?");
  await help.getByRole("button", { name: "Send question" }).click();
  expect((await supportResponse).status()).toBe(200);
  await expect(help.getByText("Sources", { exact: true })).toBeVisible();
  await expect(help.getByText("Test fixture response", { exact: true })).toBeVisible();
  expect((await (await request.get(`${API}/__fixture__/ai-stats`)).json()).capabilities).toContain("support");
});

test("provider timeout remains unavailable and guest support remains protected", async ({ page, request }) => {
  test.setTimeout(120_000);
  await page.goto("/");
  await page.getByRole("button", { name: "Help", exact: true }).click();
  let help = page.getByRole("dialog", { name: "Trace Help" });
  await help.getByLabel("Your question").fill("How do I sign in?");
  await help.getByRole("button", { name: "Send question" }).click();
  await expect(help.getByRole("alert")).toContainText("Sign in to use Trace Help");
  await help.getByRole("button", { name: "Close Trace Help" }).click();
  await signUp(page, request);
  await request.post(`${API}/__fixture__/ai-outcome/timeout`);
  await page.getByRole("button", { name: "Help", exact: true }).click();
  help = page.getByRole("dialog", { name: "Trace Help" });
  await help.getByLabel("Your question").fill("How do I sign in?");
  await help.getByRole("button", { name: "Send question" }).click();
  await expect(help.getByRole("region", { name: "Help articles" })).toBeVisible();
  await expect(help.getByText("Sources", { exact: true })).toHaveCount(0);
});
