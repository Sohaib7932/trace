import { expect, test, type Page, type APIRequestContext } from "@playwright/test";

// Real SDK calls to an isolated loopback protocol fixture, never external credentials.
test.use({ trace: "off" });
const password = "Controlled-fixture-password-47";
async function register(page: Page, request: APIRequestContext, email: string) {
  await page.goto("/sign-up");
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByLabel("Confirm password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Create account", exact: true }).click();
  await expect(page.getByText("Check your email.", { exact: true })).toBeVisible();
  const mail = await request.get(`http://127.0.0.1:8001/fixture/mail?email=${encodeURIComponent(email)}`);
  const { link } = await mail.json() as { link: string };
  expect(new URL(link).origin).toBe("http://127.0.0.1:3100");
  await page.goto(link);
  await expect(page.getByRole("heading", { name: "A home for your progress." })).toBeVisible();
  await expect(page.getByText(email, { exact: true })).toBeVisible();
}
async function login(page: Page, email: string, value = password) {
  await page.goto("/sign-in");
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(value);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
}

test("registration, verified account, authenticated learning, refresh and logout", async ({ page, request }, testInfo) => {
  test.setTimeout(90_000);
  const email = `learner-${crypto.randomUUID()}@example.test`;
  await register(page, request, email);
  await expect(page.getByText("learner", { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("account.png"), fullPage: true });
  const userId = (await page.locator("dd.font-mono").textContent())!;
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page).toHaveURL(/\/sign-in$/);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("sign-in.png"), fullPage: true });
  await page.goto("/account");
  await expect(page.getByRole("heading", { name: "Welcome back." })).toBeVisible();
  await login(page, email, "Incorrect-fixture-password");
  await expect(page.getByRole("status")).toContainText("could not be verified");
  const before = await (await request.get("http://127.0.0.1:8001/fixture/stats")).json() as { refreshes: number };
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.locator("dd.font-mono")).toHaveText(userId);
  const after = await (await request.get("http://127.0.0.1:8001/fixture/stats")).json() as { refreshes: number };
  expect(after.refreshes).toBeGreaterThan(before.refreshes);
  await page.getByRole("link", { name: "Continue learning", exact: true }).click();
  await page.getByRole("button", { name: "Start lesson", exact: true }).click();
  await page.getByLabel("The request will be rejected", { exact: true }).check();
  await page.getByLabel("Why do you expect that?").fill("The authenticated learner preserves this prediction after reload.");
  await page.getByRole("button", { name: "Lock prediction", exact: true }).click();
  await page.reload();
  await expect(page.getByRole("region", { name: "Locked prediction" })).toContainText("authenticated learner preserves");
  await page.goto("/account");
  await expect(page.locator("dd.font-mono")).toHaveText(userId);
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page).toHaveURL(/\/sign-in$/);
});

test("explicit guest claim preserves a real session and rejects a second account", async ({ page, context, browser, request }) => {
  test.setTimeout(90_000);
  await page.goto("/learn/fastapi-payload-mismatch");
  await page.getByRole("button", { name: "Start lesson", exact: true }).click();
  await page.getByLabel("The request will be rejected", { exact: true }).check();
  const prediction = "My guest prediction must survive account ownership.";
  await page.getByLabel("Why do you expect that?").fill(prediction);
  await page.getByRole("button", { name: "Lock prediction", exact: true }).click();
  await expect(page.getByRole("region", { name: "Locked prediction" })).toContainText(prediction);
  const guestCookie = (await context.cookies()).find((cookie) => cookie.name === "trace_learner")!;
  expect(Boolean(guestCookie)).toBe(true);
  await register(page, request, `claim-${crypto.randomUUID()}@example.test`);
  await page.getByRole("button", { name: "Review history claim" }).click();
  await expect(page.getByText("Attach this guest history to this account?", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Confirm history claim" }).click();
  await expect(page.getByRole("status")).toContainText("Every session is preserved");
  expect((await context.cookies()).some((cookie) => cookie.name === "trace_learner")).toBe(false);
  await page.getByRole("link", { name: "Continue learning", exact: true }).click();
  await expect(page.getByRole("region", { name: "Locked prediction" })).toContainText(prediction);
  await page.reload();
  await expect(page.getByRole("region", { name: "Locked prediction" })).toContainText(prediction);
  const other = await browser.newContext({ baseURL: "http://127.0.0.1:3100" });
  try {
    const second = await other.newPage();
    let authorization = "";
    second.on("request", (request) => {
      if (request.url() === "http://127.0.0.1:8000/api/v1/account/me") authorization = request.headers()["authorization"] ?? "";
    });
    await register(second, request, `second-${crypto.randomUUID()}@example.test`);
    await other.addCookies([guestCookie]);
    const response = await other.request.post("http://127.0.0.1:8000/api/v1/account/claim-anonymous", {
      data: {}, headers: { Authorization: authorization, Origin: "http://127.0.0.1:3100", "X-Trace-Client": "learning-web", "Idempotency-Key": crypto.randomUUID() },
    });
    expect(response.status()).toBe(401);
    await second.reload();
    await expect(second.getByText("Your account is ready.", { exact: false })).toBeVisible();
  } finally { await other.close(); }
});

test("recovery links change the provider password and invalid callbacks stay safe", async ({ page, request }) => {
  test.setTimeout(90_000);
  const email = `recovery-${crypto.randomUUID()}@example.test`;
  await register(page, request, email);
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page).toHaveURL(/\/sign-in$/);
  await page.goto("/forgot-password");
  await page.getByLabel("Email address").fill(email);
  await page.getByRole("button", { name: "Send reset link" }).click();
  await expect(page.getByRole("status")).toContainText("If an account");
  const { link } = await (await request.get(`http://127.0.0.1:8001/fixture/mail?email=${encodeURIComponent(email)}`)).json() as { link: string };
  await page.goto(link);
  await expect(page.getByRole("heading", { name: "Choose a new password." })).toBeVisible();
  const replacement = "Changed-controlled-password-89";
  await page.getByLabel("New password", { exact: true }).fill(replacement);
  await page.getByLabel("Confirm password", { exact: true }).fill(replacement);
  await page.getByRole("button", { name: "Change password", exact: true }).click();
  await expect(page).toHaveURL(/\/sign-in$/);
  await login(page, email, replacement);
  await expect(page.getByText(email, { exact: true })).toBeVisible();
  await page.goto("/auth/callback?error=access_denied&error_description=untrusted&next=https://evil.example");
  await expect(page).toHaveURL(/\/sign-in\?auth_error=link$/);
  await expect(page.getByRole("status")).toContainText("could not be completed");
  await expect(page.getByText("untrusted", { exact: true })).toHaveCount(0);
});
