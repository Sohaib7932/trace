import { expect, test, type Page } from "@playwright/test";
import { seedGuestHistory, signUp } from "./helpers/account";

// Real FastAPI fixture backend with a temporary migrated/seeded database; no API response is mocked.
test.use({ trace: "off" });
const API = "http://127.0.0.1:8000";

async function guard(page: Page, errors: string[]) {
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/api/v1/**", (route) => new URL(route.request().url()).origin === API ? route.continue() : route.abort("blockedbyclient"));
}
async function predict(page: Page) {
  await page.getByLabel("The request will be rejected", { exact: true }).check();
  await page.getByRole("button", { name: "Lock prediction", exact: true }).click();
  await expect(page.getByRole("region", { name: "Locked prediction" })).toBeVisible();
}

test("Notes: real failure evidence, fixture hint slots, correction, completion and resume", async ({ page, request }) => {
  await signUp(page, request);
  test.setTimeout(90_000);
  const errors: string[] = [];
  await guard(page, errors);
  await page.goto("/learn/fastapi-payload-mismatch");
  await page.getByRole("button", { name: "Start lesson", exact: true }).click();
  // Reason left blank: the form says what is saved, and the locked view never presents it as learner text.
  await expect(page.getByText(/If you leave this blank, Trace saves/)).toBeVisible();
  await predict(page);
  await expect(page.getByText("You didn't write a reason.")).toBeVisible();

  await page.getByRole("button", { name: /^Change field name, currently / }).click();
  await page.getByRole("option", { name: /"body"/ }).click();
  await page.getByRole("button", { name: "Check my change", exact: true }).click();
  const failed = page.getByRole("region", { name: "Verification evidence, attempt 1" });
  await expect(failed.getByRole("heading", { name: "Request rejected" })).toBeVisible();
  await expect(failed.getByText("422", { exact: true })).toBeVisible();
  await expect(failed.getByText("row_count", { exact: true })).toBeVisible();

  const guidance = page.getByRole("region", { name: "Recorded guidance" });
  await expect(guidance.getByText("0 of 3 requests used · 0 delivered")).toBeVisible();
  await guidance.getByRole("button", { name: "Request a hint" }).click();
  await expect(guidance.getByText("Hint 1 · fixture guidance")).toBeVisible();
  await expect(guidance.getByText("1 of 3 requests used · 1 delivered")).toBeVisible();

  await page.getByRole("button", { name: /^Change field name, currently / }).click();
  await page.getByRole("option", { name: /"content"/ }).click();
  await page.getByRole("button", { name: "Check my change", exact: true }).click();
  await expect(page.getByRole("region", { name: "Verification evidence, attempt 2" }).getByRole("heading", { name: "Persistence verified" })).toBeVisible();
  await expect(page.getByText("Lesson completed · verified by the server")).toBeVisible();

  await page.reload();
  await expect(page.getByRole("heading", { name: "Attempt 1 · body" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Attempt 2 · content" })).toBeVisible();
  await expect(page.getByText("Lesson completed · verified by the server")).toBeVisible();
  await expect(page.getByRole("button", { name: "Leave this attempt" })).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("an unreachable backend leaves a recoverable state with the draft intact, then the same action succeeds", async ({ page, request }) => {
  await signUp(page, request);
  test.setTimeout(90_000);
  const errors: string[] = [];
  await guard(page, errors);
  await page.goto("/learn/fastapi-payload-mismatch");
  await page.getByRole("button", { name: "Start lesson", exact: true }).click();
  await predict(page);
  await page.getByRole("button", { name: /^Change field name, currently / }).click();
  await page.getByRole("option", { name: /"content"/ }).click();
  // Simulate the backend going away for the save request only.
  await page.route("**/api/v1/sessions/*/attempts", (route) => route.request().method() === "POST" ? route.abort("connectionrefused") : route.continue());
  await page.getByRole("button", { name: "Check my change", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "couldn't reach the lesson server" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Change field name, currently content" })).toBeVisible();
  await page.unroute("**/api/v1/sessions/*/attempts");
  await page.getByRole("button", { name: "Check my change", exact: true }).click();
  await expect(page.getByRole("region", { name: "Verification evidence, attempt 1" }).getByRole("heading", { name: "Persistence verified" })).toBeVisible();
  expect(errors).toEqual([]);
});

test("leaving an attempt needs confirmation, keeps history and allows a new attempt", async ({ page, request }) => {
  await signUp(page, request);
  test.setTimeout(90_000);
  const errors: string[] = [];
  await guard(page, errors);
  await page.goto("/learn/fastapi-payload-mismatch");
  await page.getByRole("button", { name: "Start lesson", exact: true }).click();
  await predict(page);
  await page.getByRole("button", { name: "Leave this attempt" }).click();
  await expect(page.getByText(/Leave this attempt\? Its saved work stays/)).toBeVisible();
  await page.getByRole("button", { name: "Yes, leave it" }).click();
  await expect(page.getByText(/You left that attempt/)).toBeVisible();
  await page.getByRole("button", { name: "Start lesson", exact: true }).click();
  await expect(page.getByRole("form", { name: "Initial prediction" })).toBeVisible();
  expect(errors).toEqual([]);
});

test("signed in on a lesson page: the guest-history choice comes before any learner call", async ({ page, request }) => {
  test.setTimeout(120_000);
  const errors: string[] = [];
  await guard(page, errors);
  // Guest history from before the sign-in rule; the UI no longer starts guest sessions.
  await seedGuestHistory(page, "Guest history before signing in.");

  const email = `gate-${crypto.randomUUID()}@example.test`;
  const password = "Controlled-fixture-password-47";
  await page.goto("/sign-up");
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByLabel("Confirm password").fill(password);
  await page.getByRole("button", { name: "Create account", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Check your inbox" })).toBeVisible();
  const { link } = await (await request.get(`http://127.0.0.1:8001/fixture/mail?email=${encodeURIComponent(email)}`)).json() as { link: string };

  const learnerCalls: string[] = [];
  page.on("request", (r) => { if (/\/api\/v1\/(learners|sessions)/.test(r.url())) learnerCalls.push(r.url()); });
  await page.goto(link);
  await expect(page).toHaveURL(/\/account$/);
  await page.goto("/learn/fastapi-payload-mismatch");
  await expect(page.getByRole("heading", { name: "This browser has guest progress" })).toBeVisible();
  expect(learnerCalls).toEqual([]);

  await page.getByRole("button", { name: "Keep my guest progress" }).click();
  await page.getByRole("button", { name: "Yes, keep it with my account" }).click();
  await expect(page.getByRole("region", { name: "Locked prediction" })).toBeVisible();
  expect(errors).toEqual([]);
});
