import { expect, test, type Page } from "@playwright/test";
import { signUp } from "./helpers/account";

// The lesson composer and first-run guidance. No lesson-creation endpoint exists in
// openapi.json yet, so creating stays unavailable and nothing may be sent for it.
test.use({ trace: "off" });

function guard(page: Page) {
  const errors: string[] = [];
  const creationCalls: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => { if (/lessons\/custom|generat|lesson-requests/.test(request.url())) creationCalls.push(request.url()); });
  return { errors, creationCalls };
}

async function noOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
}

test("navbar to composer: one message box, a live preview, and sign-in as the next step for guests", async ({ page, isMobile }) => {
  const { errors, creationCalls } = guard(page);
  await page.goto("/today");
  if (isMobile) {
    await page.getByRole("button", { name: "Open menu" }).click();
    await page.locator("#mobile-menu").getByRole("link", { name: "Create a lesson" }).click();
  } else {
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Create a lesson" }).click();
  }
  await expect(page).toHaveURL(/\/learn\/new$/);
  await expect(page.getByRole("heading", { level: 1 })).toContainText("What do you want to learn?");
  // The composer page has its own primary action, so the navbar has none.
  await expect(page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Create a lesson" })).toHaveCount(0);
  const box = page.getByRole("textbox", { name: "What do you want to learn?", exact: true });
  await expect(box).toHaveCount(1);
  await box.fill("Teach me FastAPI request validation with predict-and-fix exercises");
  const preview = page.getByRole("region", { name: /FastAPI request validation/ });
  await expect(preview.getByText("Python · FastAPI")).toBeVisible();
  // Created lessons are never run on a server: answer key + practice only, never "real server".
  await expect(preview.getByText("Checked against an answer key")).toBeVisible();
  await expect(preview.getByText(/Checked on a real server/)).toHaveCount(0);
  await box.fill("Explain closures in JavaScript");
  await expect(page.getByRole("region", { name: /closures in JavaScript/ }).getByText("JavaScript", { exact: true })).toBeVisible();
  // Guests: the one primary action is signing in; nothing is sent.
  await expect(page.getByRole("link", { name: "Sign in to create this lesson" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Create lesson" })).toHaveCount(0);
  await expect(page.getByText("Draft saved")).toBeVisible();
  await page.reload();
  await expect(page.getByRole("textbox", { name: "What do you want to learn?", exact: true })).toHaveValue("Explain closures in JavaScript");
  await noOverflow(page);
  expect(creationCalls).toEqual([]);
  expect(errors).toEqual([]);
});

test("keyboard only: reach the composer, use an example, open How it works", async ({ page, isMobile }) => {
  test.skip(isMobile, "Keyboard path checked on desktop");
  const { errors } = guard(page);
  await page.goto("/learn/new");
  const example = page.getByRole("button", { name: "Python async order" });
  for (let i = 0; i < 40 && !(await example.evaluate((el) => el === document.activeElement)); i++) await page.keyboard.press("Tab");
  await expect(example).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("textbox", { name: "What do you want to learn?", exact: true })).toBeFocused();
  await expect(page.getByRole("textbox", { name: "What do you want to learn?", exact: true })).toHaveValue(/async and await/);
  const how = page.getByRole("button", { name: "How it works" });
  await how.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog", { name: "How Trace lessons work" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(how).toBeFocused();
  expect(errors).toEqual([]);
});

test("new and returning learners: a first-visit hint, then a Continue card once a lesson is started", async ({ page, request }) => {
  test.setTimeout(120_000);
  const { errors } = guard(page);
  await signUp(page, request);
  await page.goto("/learn");
  await expect(page.getByText("New here? Start with lesson 1. It takes about 5 minutes.")).toBeVisible();
  await expect(page.getByRole("region", { name: "Continue" })).toHaveCount(0);
  await page.getByRole("article", { name: /Follow the note/ }).getByRole("link", { name: "Start", exact: true }).click();
  await page.getByRole("button", { name: "Start lesson", exact: true }).click();
  await page.getByLabel("The request will be rejected", { exact: true }).check();
  await page.getByRole("button", { name: "Lock prediction", exact: true }).click();
  await expect(page.getByRole("region", { name: "Locked prediction" })).toBeVisible();
  await page.goto("/learn");
  await expect(page.getByRole("region", { name: "Continue" })).toBeVisible();
  await expect(page.getByText(/New here\?/)).toHaveCount(0);
  expect(errors).toEqual([]);
});

for (const width of [1440, 1024, 768, 390, 320]) {
  test(`composer and library have no horizontal overflow at ${width}px`, async ({ page }) => {
    const { errors } = guard(page);
    await page.setViewportSize({ width, height: 900 });
    for (const path of ["/learn", "/learn/new"]) {
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await noOverflow(page);
    }
    expect(errors).toEqual([]);
  });
}
