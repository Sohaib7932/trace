import { expect, type APIRequestContext, type Page } from "@playwright/test";

// Real lessons are for signed-in learners. These helpers use the isolated loopback auth
// fixture (:8001) and the repo's test backend; never external credentials.
export const API = "http://127.0.0.1:8000";
export const PASSWORD = "Controlled-fixture-password-47";

/** Creates and confirms a fresh account; the page ends signed in on /account. */
export async function signUp(page: Page, request: APIRequestContext, prefix = "learner") {
  const email = `${prefix}-${crypto.randomUUID()}@example.test`;
  await page.goto("/sign-up");
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByLabel("Confirm password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Create account", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Check your inbox" })).toBeVisible();
  const mail = await request.get(`http://127.0.0.1:8001/fixture/mail?email=${encodeURIComponent(email)}`);
  const { link } = await mail.json() as { link: string };
  await page.goto(link);
  await expect(page).toHaveURL(/\/account$/);
  return email;
}

/**
 * Guest history from before the sign-in rule (or another client): the UI no longer lets guests
 * start lessons, so the claim flow is exercised by creating that history through the real API
 * with this browser's guest cookie, then telling the app which session it was.
 */
export async function seedGuestHistory(page: Page, reasoning: string, lessonId = "fastapi-payload-mismatch") {
  const headers = { Origin: "http://127.0.0.1:3100", "X-Trace-Client": "learning-web", "Content-Type": "application/json" };
  const post = async (path: string, data: object) => {
    const response = await page.request.post(`${API}/api/v1${path}`, { data, headers: { ...headers, "Idempotency-Key": crypto.randomUUID() } });
    expect(response.ok(), `${path} → ${response.status()}`).toBe(true);
    return response.json() as Promise<{ id: string }>;
  };
  await post("/learners/anonymous", {});
  const session = await post("/sessions", { lesson_id: lessonId, version: "1.0.0" });
  await post(`/sessions/${session.id}/prediction`, { selected_answer: "rejected", reasoning });
  await page.goto("/");
  await page.evaluate(([key, id]) => localStorage.setItem(key, id), [`trace.session.${lessonId}`, session.id]);
  return session.id;
}
