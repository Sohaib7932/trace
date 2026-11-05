import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

// Real HTTP through the fixture backend (mock provider transport): no Gemini, no key.
const API = "http://127.0.0.1:8110";
const AUTH = "http://127.0.0.1:8111";
const PASSWORD = "Controlled-fixture-password-47";

async function signUp(page: Page, request: APIRequestContext) {
  const email = `custom-${crypto.randomUUID()}@example.test`;
  await page.goto("/sign-up");
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByLabel("Confirm password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Create account", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Check your inbox" })).toBeVisible();
  const { link } = await (await request.get(`${AUTH}/fixture/mail?email=${encodeURIComponent(email)}`)).json() as { link: string };
  await page.goto(link);
  await expect(page).toHaveURL(/\/account$/);
}

function guard(page: Page) {
  const errors: string[] = [];
  const keyLeaks: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("response", async (response) => {
    if (!response.url().startsWith(`${API}/api/v1/custom-lessons`) || response.request().method() === "OPTIONS") return;
    const body = await response.text().catch(() => "");
    if (/correct_option/.test(body)) keyLeaks.push(response.url());
  });
  return { errors, keyLeaks };
}

async function noOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
}

async function compose(page: Page, prompt: string) {
  await page.goto("/learn/new");
  const box = page.getByLabel("What do you want to learn?");
  await box.fill(prompt);
  await expect(page.getByRole("button", { name: "Create lesson" })).toBeEnabled();
  await page.getByRole("button", { name: "Create lesson" }).click();
  await expect(page).toHaveURL(/\/learn\/requests\/[0-9a-f-]+$/);
}

test("hub to composer to tracker to lesson to a server-checked answer, then My lessons and delete", async ({ page, request }) => {
  test.setTimeout(120_000);
  const { errors, keyLeaks } = guard(page);
  await signUp(page, request);
  await page.goto("/learn/my");
  await expect(page.getByRole("heading", { name: "No lessons yet" })).toBeVisible();
  await page.getByRole("link", { name: /^Create your first lesson/ }).click();
  await expect(page).toHaveURL(/\/learn\/new$/);
  await compose(page, "Teach me how FastAPI validates a request body, with predict-and-fix exercises.");
  await expect(page.getByRole("heading", { name: "Your lesson is ready" })).toBeVisible({ timeout: 20_000 });
  await page.getByRole("link", { name: "Open your lesson" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Reading code carefully");
  await expect(page.getByText("AI-created").first()).toBeVisible();
  await expect(page.getByText("Checked against an answer key").first()).toBeVisible();
  await expect(page.getByText(/Checked on a real server/)).toHaveCount(0);

  // Challenge 1: read, predict (locked), change a line in the code, verify; wrong, then right.
  const first = page.getByRole("region", { name: /Challenge 1:/ });
  await first.getByText("It always fails").click();
  await first.getByRole("button", { name: "Lock prediction" }).click();
  await expect(first.getByText("Locked", { exact: true })).toBeVisible();
  await first.getByRole("button", { name: "Try a change in the code" }).click();
  await first.getByRole("button", { name: "Change line 1" }).click();
  await first.getByRole("textbox", { name: "Line 1: your change" }).fill("from pydantic import BaseModel, Field");
  await first.getByRole("textbox", { name: "Line 1: your change" }).press("Enter");
  // A wrong answer stays on Modify with a "Not yet" note, as in the demo.
  await expect(first.getByText(/Your answer doesn't match the lesson's answer key\./).first()).toBeVisible();
  await first.getByText("It describes the expected shape").click();
  await first.getByRole("button", { name: /Check my (answer|change)/ }).click();
  await expect(first.getByText("Your answer matches the lesson's answer key.").first()).toBeVisible();
  await expect(first.getByText("Challenge 1 done")).toBeVisible();
  await expect(page.getByText("1 of 3 challenges done")).toBeVisible();
  await expect(page.getByText(/verified by the server|ran your code/i)).toHaveCount(0);

  // The lesson tutor reads this lesson and step; hints come from the lesson.
  await page.getByRole("button", { name: /Lesson tutor/ }).click();
  const tutor = page.getByRole("dialog", { name: "Lesson tutor" });
  await expect(tutor.getByText(/Lesson: Reading code carefully/)).toBeVisible();
  await tutor.getByRole("button", { name: "Explain this concept" }).click();
  await expect(tutor.getByRole("article")).toContainText("From this lesson");
  await tutor.getByRole("button", { name: "Close lesson tutor" }).click();

  // Reload: progress comes back from the server and the next unfinished challenge opens.
  await page.reload();
  await expect(page.getByRole("region", { name: /Challenge 2:/ })).toBeVisible();
  await page.getByRole("button", { name: "Challenge 3" }).click();
  const third = page.getByRole("region", { name: /Challenge 3:/ });
  await expect(third.getByText("Practice only", { exact: true })).toBeVisible();
  await third.getByLabel("Your explanation").fill("It describes the data the code expects.");
  await third.getByRole("button", { name: "Lock it in" }).click();
  await third.getByRole("button", { name: /Check my answer/ }).click();
  await expect(third.getByText("Compare your explanation with the lesson's example.").first()).toBeVisible();
  await expect(page.getByText("2 of 3 challenges done")).toBeVisible();
  await noOverflow(page);

  // Saved on the server: still listed after a full reload, with its progress.
  // Saved on the server: offered on /learn, and still listed on /learn/my after a full reload.
  await page.goto("/learn");
  await expect(page.getByRole("region", { name: "Continue" }).getByRole("link", { name: /^Continue Reading code carefully/ })).toBeVisible();
  await page.getByRole("navigation", { name: "Lesson library" }).getByRole("link", { name: "My lessons" }).click();
  await expect(page).toHaveURL(/\/learn\/my$/);
  await page.reload();
  const card = page.getByRole("article").filter({ hasText: "Reading code carefully" });
  await expect(card).toContainText("In progress · 2 of 3 challenges");
  await card.getByRole("link", { name: /^Open Reading code carefully/ }).click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Reading code carefully");
  await page.goto("/learn/my");
  await card.getByRole("button", { name: /^More actions for/ }).click();
  await card.getByRole("button", { name: "Delete", exact: true }).click();
  await page.getByRole("dialog", { name: "Delete this lesson?" }).getByRole("button", { name: "Delete", exact: true }).click();
  await expect(page.getByRole("heading", { name: "No lessons yet" })).toBeVisible();
  await noOverflow(page);
  expect(keyLeaks).toEqual([]);
  expect(errors).toEqual([]);
});

test("tracker shows a policy rejection and an invalid draft honestly, with the right next step", async ({ page, request }) => {
  test.setTimeout(120_000);
  const { errors } = guard(page);
  await signUp(page, request);
  await compose(page, "Write me a poem about the sea in Python [fixture:declined]");
  await expect(page.getByRole("heading", { name: "Trace can't create this lesson" })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText(/doesn't look like a programming topic/)).toBeVisible();
  await expect(page.getByRole("link", { name: "Edit your request" })).toBeVisible();
  await compose(page, "Teach me Python decorators please [fixture:invalid]");
  await expect(page.getByRole("heading", { name: "This lesson couldn't be created" })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/didn't pass Trace's checks/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Try again" })).toBeVisible();
  expect(errors).toEqual([]);
});

test("cancel stops a running request", async ({ page, request }) => {
  test.setTimeout(90_000);
  const { errors } = guard(page);
  await signUp(page, request);
  await compose(page, "Teach me JavaScript closures with examples [fixture:slow]");
  await page.getByRole("button", { name: "Cancel request" }).click();
  await expect(page.getByRole("heading", { name: "You cancelled this request" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Try again" })).toBeVisible();
  expect(errors).toEqual([]);
});

test("keyboard only: compose with an example, send, and open the lesson", async ({ page, request, isMobile }) => {
  test.skip(isMobile, "Keyboard path checked on desktop");
  test.setTimeout(90_000);
  const { errors } = guard(page);
  await signUp(page, request);
  await page.goto("/learn/new");
  const example = page.getByRole("button", { name: "SQL duplicate rows" });
  for (let i = 0; i < 40 && !(await example.evaluate((el) => el === document.activeElement)); i++) await page.keyboard.press("Tab");
  await expect(example).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByLabel("What do you want to learn?")).toBeFocused();
  await page.keyboard.press("Control+Enter");
  await expect(page).toHaveURL(/\/learn\/requests\//);
  const open = page.getByRole("link", { name: "Open your lesson" });
  await expect(open).toBeVisible({ timeout: 20_000 });
  await open.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Reading code carefully");
  expect(errors).toEqual([]);
});

test("guests are asked to sign in and nothing is sent", async ({ page }) => {
  const calls: string[] = [];
  page.on("request", (r) => { if (r.url().includes("/custom-lessons")) calls.push(r.url()); });
  await page.goto("/learn/new");
  await page.getByLabel("What do you want to learn?").fill("Teach me FastAPI request validation");
  await expect(page.getByRole("link", { name: "Sign in to create this lesson" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Create lesson" })).toHaveCount(0);
  await noOverflow(page);
  expect(calls).toEqual([]);
});
