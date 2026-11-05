import { expect, test, type Page } from "@playwright/test";
import { signUp } from "./helpers/account";

// AI surfaces run on labelled mocks (NEXT_PUBLIC_AI_MODE unset = mock). Learning data comes from
// the repo's test backend with a temporary database; no AI provider is ever called.
test.use({ trace: "off" });
const API = "http://127.0.0.1:8000";

async function guard(page: Page, errors: string[]) {
  page.on("pageerror", (error) => errors.push(error.message));
  // Only the test backend and the app itself are reachable; nothing else (no provider, no hosted API).
  await page.route(/^https?:\/\/(?!127\.0\.0\.1)/, (route) => route.abort("blockedbyclient"));
  await page.route("**/api/v1/**", (route) => new URL(route.request().url()).origin === API ? route.continue() : route.abort("blockedbyclient"));
}
async function askHelp(page: Page, question: string) {
  const launcher = page.getByRole("button", { name: "Help", exact: true });
  await launcher.click();
  const dialog = page.getByRole("dialog", { name: "Trace Help" });
  await expect(dialog.getByRole("button", { name: "Demo responses" })).toBeVisible();
  await dialog.getByRole("button", { name: question }).click();
  await expect(dialog.getByText("Sources")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(launcher).toBeFocused();
}
async function openTutor(page: Page) {
  const bar = page.locator(".tutor-bar");
  if (await bar.isVisible()) {
    await bar.getByRole("button", { name: /Lesson tutor/ }).click();
    return page.getByRole("dialog", { name: "Lesson tutor" });
  }
  return page.getByRole("complementary", { name: "Lesson tutor" });
}
async function startLesson(page: Page) {
  await page.goto("/learn/fastapi-payload-mismatch");
  await page.locator("label", { hasText: /The request will be rejected/ }).click();
  await page.getByRole("button", { name: "Lock prediction", exact: true }).click();
  await expect(page.getByRole("region", { name: "Locked prediction" })).toBeVisible();
}

test("Trace Help is on the homepage, sign-in, hub, a lesson and account, and answers with sources", async ({ page, request }) => {
  test.setTimeout(120_000);
  const errors: string[] = [];
  await guard(page, errors);
  for (const path of ["/", "/sign-in", "/learn"]) {
    await page.goto(path);
    await askHelp(page, "How do follow-ups work?");
  }
  await signUp(page, request, "help");
  await askHelp(page, "Where is my progress?");
  await startLesson(page);
  await askHelp(page, "What is a fixture hint?");
  expect(errors).toEqual([]);
});

test("lesson: the real fixture hint and the demo tutor stay separate from verification", async ({ page, request }) => {
  test.setTimeout(120_000);
  await signUp(page, request);
  const errors: string[] = [];
  await guard(page, errors);
  await startLesson(page);
  await page.getByRole("button", { name: /^Change field name, currently / }).click();
  await page.getByRole("option", { name: /"body"/ }).click();
  await page.getByRole("button", { name: "Check my change", exact: true }).click();
  await expect(page.getByRole("region", { name: "Verification evidence, attempt 1" }).getByText("422", { exact: true })).toBeVisible();

  const tutor = await openTutor(page);
  await expect(tutor.getByRole("button", { name: "Demo responses" })).toBeVisible();
  const hintRequest = page.waitForResponse((r) => r.url().includes("/hints") && r.request().method() === "POST");
  await tutor.getByRole("button", { name: /Give me a hint/ }).click();
  expect((await hintRequest).status()).toBe(201);
  await expect(tutor.getByRole("region", { name: "Fixture guidance" })).toContainText("1 of 3 requests used · 1 delivered");
  await tutor.getByRole("button", { name: "Why did this fail?" }).click();
  await expect(tutor.getByText(/The server answered 422/).first()).toBeVisible();
  await expect(tutor.getByText(/AI explanation \(demo\)/).first()).toBeVisible();
  await expect(tutor).not.toContainText(/you('| a)re (right|correct)/i);
  if (await page.locator(".tutor-bar").isVisible()) await page.keyboard.press("Escape");
  // The demo tutor changed nothing real: still one attempt, still needs revision, one hint used.
  await page.reload();
  await expect(page.getByRole("heading", { name: /Your change · attempt 1/ })).toBeVisible();
  await expect(page.getByRole("region", { name: "Recorded guidance" }).getByText(/1 of 3 hints used/)).toBeVisible();
  await expect(page.getByText("Lesson completed · verified by the server")).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("/today: interests, sequential demo steps and a sign-in link to the real lesson", async ({ page }) => {
  const errors: string[] = [];
  await guard(page, errors);
  await page.goto("/today");
  await expect(page.getByText("Design preview: daily exercises are not connected to the backend yet.")).toBeVisible();
  await page.getByRole("button", { name: "Fitness tracking" }).click();
  await page.getByRole("button", { name: "Save interests" }).click();
  const cards = page.getByRole("article");
  await expect(cards).toHaveCount(3);
  await expect(cards.nth(1)).toContainText("Fitness tracking");
  await expect(cards.nth(1).getByText("Locked")).toBeVisible();
  await cards.nth(0).getByRole("button", { name: "Mark as done (demo)" }).click();
  await expect(cards.nth(1).getByRole("button", { name: "Mark as done (demo)" })).toBeVisible();
  await cards.nth(1).getByRole("button", { name: "Mark as done (demo)" }).click();
  // Guests only get demos: the real lesson step asks them to sign in first.
  await expect(cards.nth(2).getByRole("link", { name: "Sign in to start" })).toHaveAttribute("href", "/sign-in?next=%2Flearn%2Ffastapi-payload-mismatch");
  await expect(cards.nth(2).getByText("Real lesson · server-verified")).toBeVisible();
  expect(errors).toEqual([]);
});

test("keyboard only: reach Trace Help, ask, read sources and close with focus restored", async ({ page, isMobile }) => {
  test.skip(isMobile, "Keyboard path checked on desktop");
  await page.goto("/learn");
  const launcher = page.getByRole("button", { name: "Help", exact: true });
  await expect(launcher).toBeVisible();
  for (let i = 0; i < 80 && !(await launcher.evaluate((el) => el === document.activeElement)); i++) await page.keyboard.press("Tab");
  await expect(launcher).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByLabel("Your question")).toBeFocused();
  await page.keyboard.type("How do I sign up?");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog", { name: "Trace Help" }).getByRole("link", { name: "Creating an account" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(launcher).toBeFocused();
});

test("the Help launcher never overlaps the tutor or the submit button at 320, 390, 768 and 1280", async ({ page, request, isMobile }) => {
  test.skip(isMobile, "Widths set explicitly");
  test.setTimeout(120_000);
  await signUp(page, request);
  await startLesson(page);
  const overlap = (a: { x: number; y: number; width: number; height: number } | null, b: typeof a) =>
    Boolean(a && b && a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height);
  for (const width of [320, 390, 768, 1280]) {
    await page.setViewportSize({ width, height: 800 });
    await page.waitForTimeout(400);
    const submit = page.getByRole("button", { name: "Check my change", exact: true });
    await submit.scrollIntoViewIfNeeded();
    const launcher = await page.locator(".help-launcher").boundingBox();
    const tutor = await page.locator(".tutor-bar").boundingBox();
    expect(overlap(launcher, tutor), `tutor at ${width}`).toBe(false);
    expect(overlap(launcher, await submit.boundingBox()), `submit at ${width}`).toBe(false);
  }
});
