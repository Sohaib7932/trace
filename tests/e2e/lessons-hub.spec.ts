import { expect, test, type Page } from "@playwright/test";

// Real FastAPI fixture backend; no API response is mocked.
test.use({ trace: "off" });

function guard(page: Page, errors: string[]) {
  page.on("pageerror", (error) => errors.push(error.message));
  return page.route("**/api/v1/**", (route) => new URL(route.request().url()).origin === "http://127.0.0.1:8000" ? route.continue() : route.abort("blockedbyclient"));
}
async function noOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
}

test("'Try a lesson' and 'Try Trace' lead to the lessons hub; 'See how Trace works' stays on the demo", async ({ page }) => {
  const errors: string[] = [];
  await guard(page, errors);
  await page.goto("/");
  await expect(page.getByRole("link", { name: "See how Trace works" })).toHaveAttribute("href", "#demo");
  await expect(page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Try Trace" })).toHaveAttribute("href", "/learn");
  // The hero CTA (the final CTA uses the same label and destination).
  await page.locator("#top").getByRole("link", { name: "Try a lesson" }).click();
  await expect(page).toHaveURL(/\/learn$/);
  await expect(page.getByRole("heading", { level: 1 })).toContainText("real code");
  await expect(page.getByText("0 of 2 lessons completed", { exact: true })).toBeVisible();
  await noOverflow(page);
  expect(errors).toEqual([]);
});

test("the transfer lesson stays locked until the first is complete, then the completion panel offers it", async ({ page }, testInfo) => {
  test.setTimeout(120_000);
  const errors: string[] = [];
  await guard(page, errors);
  await page.goto("/learn");
  const transfer = page.getByRole("article", { name: "The Nested Payload Problem" });
  await expect(transfer.getByText("Locked", { exact: true })).toBeVisible();
  await expect(transfer.getByText(/Opens when you complete/)).toBeVisible();
  await expect(transfer.getByRole("link")).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath("learn-new.png"), fullPage: true });

  await page.getByRole("link", { name: "Start lesson 1" }).click();
  await expect(page.getByRole("navigation", { name: "Breadcrumb" }).getByRole("link", { name: "Lessons" })).toBeVisible();
  await page.getByRole("button", { name: "Start lesson", exact: true }).click();
  await page.getByLabel("The request will be rejected", { exact: true }).check();
  await page.getByLabel("Why do you expect that?").fill("The sender and receiver use different names.");
  await page.getByRole("button", { name: "Lock prediction", exact: true }).click();
  await page.getByRole("radio", { name: "body", exact: true }).check();
  await page.getByRole("button", { name: "Check my change", exact: true }).click();
  await expect(page.getByRole("region", { name: "Verification evidence, attempt 1" }).getByText("422", { exact: true })).toBeVisible();
  // Not completed on the server yet: no completion panel, transfer still locked.
  await expect(page.getByText("Lesson completed · verified by the server")).toHaveCount(0);
  await page.goto("/learn");
  await expect(page.getByRole("article", { name: "The Nested Payload Problem" }).getByText("Locked", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Continue where you left off" })).toBeVisible();

  await page.getByRole("link", { name: "Pick up the lesson" }).click();
  await page.getByRole("radio", { name: "content", exact: true }).check();
  await page.getByRole("button", { name: "Check my change", exact: true }).click();
  const panel = page.getByRole("region", { name: "Follow the note: from form to database" });
  await expect(panel.getByText("Lesson completed · verified by the server")).toBeVisible();
  await expect(panel.getByText("Verified after revision (2 attempts)")).toBeVisible();
  await expect(panel.getByRole("link", { name: "Back to lessons" })).toHaveAttribute("href", "/learn");
  await page.screenshot({ path: testInfo.outputPath("completion.png"), fullPage: false });
  await panel.getByRole("link", { name: /Next lesson/ }).click();
  await expect(page).toHaveURL(/\/learn\/fastapi-nested-payload-transfer$/);
  await page.goto("/learn");
  await expect(page.getByText("1 of 2 lessons completed", { exact: true })).toBeVisible();
  await expect(page.getByRole("article", { name: "The Nested Payload Problem" }).getByRole("link", { name: "Start lesson" })).toBeVisible();
  await noOverflow(page);
  expect(errors).toEqual([]);
});

test("sign-in and sign-up validate inline and keep wrong-credential messages generic", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/sign-up");
  await page.getByLabel("Email address").fill("not-an-email");
  await page.getByLabel("Password", { exact: true }).fill("short");
  await page.getByLabel("Confirm password").focus();
  await expect(page.getByText("Enter an email address like name@example.com.")).toBeVisible();
  await expect(page.getByText("Use at least 12 characters.")).toBeVisible();
  await expect(page.getByLabel("Email address")).toHaveAttribute("aria-invalid", "true");
  await noOverflow(page);
  await page.goto("/sign-in");
  await page.getByLabel("Email address").fill("nobody@example.test");
  await page.getByLabel("Password", { exact: true }).fill("Wrong-password-123");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Email or password could not be verified");
  await noOverflow(page);
  expect(errors).toEqual([]);
});

test("signed-in visitors are sent from sign-in to their account, and the navbar shows Account only", async ({ page, request }) => {
  test.setTimeout(90_000);
  const email = `nav-${crypto.randomUUID()}@example.test`;
  const password = "Controlled-fixture-password-47";
  await page.goto("/sign-up");
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByLabel("Confirm password").fill(password);
  await page.getByRole("button", { name: "Create account", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Check your inbox" })).toBeVisible();
  await expect(page.getByRole("button", { name: /Resend available in \d+s/ })).toBeDisabled();
  const { link } = await (await request.get(`http://127.0.0.1:8001/fixture/mail?email=${encodeURIComponent(email)}`)).json() as { link: string };
  await page.goto(link);
  await expect(page).toHaveURL(/\/account$/);
  await page.goto("/sign-in");
  await expect(page).toHaveURL(/\/account$/);
  await page.goto("/sign-up");
  await expect(page).toHaveURL(/\/account$/);
  const nav = page.getByRole("navigation", { name: "Main" });
  await expect(nav.getByRole("link", { name: "Account", exact: true })).toBeVisible();
  await expect(nav.getByRole("link", { name: "Sign in", exact: true })).toHaveCount(0);
});

test("keyboard alone can reach a lesson from the hub", async ({ page, isMobile }) => {
  test.skip(isMobile, "Keyboard path checked on desktop");
  await page.goto("/learn");
  await expect(page.getByRole("link", { name: "Start lesson 1" })).toBeVisible();
  for (let i = 0; i < 40; i++) {
    await page.keyboard.press("Tab");
    const name = await page.evaluate(() => document.activeElement?.textContent?.trim());
    if (name === "Start lesson 1") break;
  }
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/learn\/fastapi-payload-mismatch$/);
  await expect(page.getByRole("button", { name: "Start lesson", exact: true })).toBeVisible();
  // Keep tabbing until the lesson's own start button has focus.
  let reached = false;
  for (let i = 0; i < 30 && !reached; i++) {
    await page.keyboard.press("Tab");
    reached = await page.evaluate(() => document.activeElement?.textContent?.trim() === "Start lesson");
  }
  expect(reached).toBe(true);
});
