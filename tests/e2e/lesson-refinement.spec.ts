import { expect, test, type Page } from "@playwright/test";
import { signUp } from "./helpers/account";

// Failure traces could persist raw test cookies. Keep credential-bearing traces off.
test.use({ trace: "off" });

function guard(page: Page) {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  return errors;
}

/** No code window scrolls sideways: every code body fits its own width. */
async function expectNoCodeScroll(page: Page) {
  const overflow = await page.locator("figure pre").evaluateAll((pres) =>
    pres.map((pre) => { const box = pre.parentElement!; return box.scrollWidth - box.clientWidth; }).filter((d) => d > 1));
  expect(overflow).toEqual([]);
  const pageOverflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(pageOverflow).toBeLessThanOrEqual(0);
}

async function predict(page: Page, label: string) {
  await page.getByRole("button", { name: "Start lesson" }).click();
  await page.getByLabel(label, { exact: true }).check();
  await page.getByRole("button", { name: "Lock prediction", exact: true }).click();
  await expect(page.getByRole("region", { name: "Locked prediction" })).toBeVisible();
}

for (const width of [1280, 1024, 768, 390]) {
  test(`no horizontal code scrolling at ${width}px in either lesson`, async ({ page, request }) => {
    test.setTimeout(90_000);
    const errors = guard(page);
    await signUp(page, request);
    await page.setViewportSize({ width, height: 900 });
    for (const path of ["/learn/fastapi-payload-mismatch", "/learn/fastapi-nested-payload-transfer"]) {
      await page.goto(path);
      await expect(page.locator("figure pre").first()).toBeVisible();
      await expectNoCodeScroll(page);
    }
    expect(errors).toEqual([]);
  });
}

test("notes: keyboard-only in-code edit, then a real failed and passed run", async ({ page, request }) => {
  test.setTimeout(120_000);
  const errors = guard(page);
  await signUp(page, request);
  await page.goto("/learn/fastapi-payload-mismatch");
  await predict(page, "The request will be rejected");
  const chip = page.getByRole("button", { name: "Change field name, currently body" });
  // Prediction can render before its journey refresh settles. focus() does not
  // wait for enabled controls; assert readiness before sending global keyboard input.
  await expect(chip).toBeEnabled();
  await chip.focus();
  await expect(chip).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(page.getByRole("listbox", { name: "Field name" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(chip).toBeFocused();
  // Original first: a real failed run.
  const check = page.getByRole("button", { name: "Check my change", exact: true });
  await expect(check).toBeEnabled();
  await check.focus();
  await expect(check).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("region", { name: "Verification evidence, attempt 1" }).getByText("422", { exact: true })).toBeVisible();
  await expectNoCodeScroll(page);
  // Then the edit, by keyboard only.
  await expect(chip).toBeEnabled();
  await chip.focus();
  await expect(chip).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("button", { name: "Change field name, currently content" })).toBeFocused();
  await page.getByLabel(/What changed and why/).fill("The schema expects content.");
  await expect(check).toBeEnabled();
  await check.focus();
  await expect(check).toBeFocused();
  await page.keyboard.press("Enter");
  const passed = page.getByRole("region", { name: "Verification evidence, attempt 2" });
  await expect(passed.getByText("201", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Session complete", exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});

test("tutor: context line, collapse at desktop, drawer below 1280px", async ({ page, request }, testInfo) => {
  test.skip(testInfo.project.name.includes("mobile"), "Resizes a desktop window; the phone drawer is covered in ai-surfaces.spec.ts");
  test.setTimeout(90_000);
  const errors = guard(page);
  await signUp(page, request);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/learn/fastapi-payload-mismatch");
  const tutor = page.getByRole("complementary", { name: "Lesson tutor" });
  await expect(tutor.getByText(/Lesson: .+\. Step: Read the code/)).toBeVisible();
  await predict(page, "The request will be rejected");
  await expect(tutor.getByText(/Step: Change the code/)).toBeVisible();
  await tutor.getByRole("button", { name: "Explain this concept" }).click();
  await expect(tutor.getByText(/AI explanation \(demo\)/).first()).toBeVisible();
  await tutor.getByRole("button", { name: "Collapse the lesson tutor" }).click();
  await expect(page.getByRole("button", { name: "Expand the lesson tutor" })).toBeFocused();
  await page.getByRole("button", { name: "Expand the lesson tutor" }).click();
  await expect(tutor.getByText(/AI explanation \(demo\)/).first()).toBeVisible();

  await page.setViewportSize({ width: 1100, height: 800 });
  await page.getByRole("button", { name: /Lesson tutor/ }).click();
  const drawer = page.getByRole("dialog", { name: "Lesson tutor" });
  await expect(drawer).toBeVisible();
  const box = (await drawer.boundingBox())!;
  expect(box.x + box.width).toBeGreaterThan(1080); // right-edge drawer
  expect(box.width).toBeLessThanOrEqual(400);
  await page.keyboard.press("Escape");
  await expect(drawer).toHaveCount(0);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: /Lesson tutor/ }).click();
  await expect(page.getByRole("dialog", { name: "Lesson tutor" })).toBeVisible();
  await page.getByRole("button", { name: "Close lesson tutor" }).click();
  expect(errors).toEqual([]);
});

test("my lessons and saved lessons stay gated for guests, with no request", async ({ page }) => {
  const errors = guard(page);
  const requests: string[] = [];
  page.on("request", (request) => { if (/\/api\/v1\/(?:learning-guides|custom-lessons|lessons\/custom)/.test(request.url())) requests.push(request.url()); });
  await page.goto("/learn/my");
  await expect(page.getByRole("heading", { name: "Sign in to see your lessons" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Lesson library" }).getByRole("link", { name: "My lessons" })).toHaveAttribute("aria-current", "page");
  await page.goto("/learn/guides");
  await expect(page.getByText("Lessons you create will appear here.")).toBeVisible();
  await page.getByRole("textbox", { name: "What do you want to learn?", exact: true }).fill("FastAPI authentication");
  const create = page.getByRole("button", { name: "Create lesson" });
  await expect(create).toBeDisabled();
  await expect(page.getByText("Sign in to create a lesson.")).toBeVisible();
  await expect(page.locator("main")).not.toContainText(/\bguides?\b/i);
  expect(requests).toEqual([]);
  expect(errors).toEqual([]);
});

test("library: the switcher moves between Trace lessons and My lessons; the old tab URL redirects", async ({ page, request }) => {
  const errors = guard(page);
  await signUp(page, request);
  const requests: string[] = [];
  page.on("request", (request) => { if (/\/api\/v1\/(?:learning-guides|custom-lessons|lessons\/custom)/.test(request.url()) && request.method() !== "GET") requests.push(request.url()); });
  await page.goto("/learn");
  await expect(page.getByRole("heading", { name: "Trace lessons" })).toBeVisible();
  await page.getByRole("navigation", { name: "Lesson library" }).getByRole("link", { name: "My lessons" }).click();
  await expect(page).toHaveURL(/\/learn\/my$/);
  await expect(page.getByRole("heading", { name: "No lessons yet" })).toBeVisible();
  await expect(page.getByText(/Coming soon/i)).toHaveCount(0);
  await page.goto("/learn?tab=my");
  await expect(page).toHaveURL(/\/learn\/my(?:\?|$)/);
  await page.getByRole("link", { name: "SQL duplicate rows" }).click();
  await expect(page).toHaveURL(/\/learn\/new$/);
  await expect(page.getByRole("textbox", { name: "What do you want to learn?", exact: true })).toHaveValue(/SQL joins/);
  // The example only fills the composer; nothing is created or sent.
  expect(requests).toEqual([]);
  expect(errors).toEqual([]);
});

test("guests only get demos: lessons ask for sign-in and no learner request is made", async ({ page }) => {
  const errors = guard(page);
  const learnerCalls: string[] = [];
  page.on("request", (r) => { if (/\/api\/v1\/(learners|sessions|lessons)/.test(r.url())) learnerCalls.push(r.url()); });
  for (const lesson of ["fastapi-payload-mismatch", "fastapi-nested-payload-transfer"]) {
    await page.goto(`/learn/${lesson}`);
    await expect(page.getByRole("heading", { name: "Sign in to start this lesson" })).toBeVisible();
    await expect(page.getByRole("region", { name: "Sign in to start this lesson" }).getByRole("link", { name: "Sign in", exact: true })).toHaveAttribute("href", `/sign-in?next=%2Flearn%2F${lesson}`);
    await expect(page.getByRole("button", { name: "Start lesson" })).toHaveCount(0);
  }
  await page.goto("/learn");
  await page.getByRole("link", { name: "Sign in to start Follow the note" }).click();
  await expect(page).toHaveURL(/\/sign-in\?next=%2Flearn%2Ffastapi-payload-mismatch$/);
  expect(learnerCalls).toEqual([]);
  expect(errors).toEqual([]);
});

test("signing in from a lesson's gate returns to that lesson", async ({ page, request }) => {
  test.setTimeout(90_000);
  const email = await signUp(page, request);
  await page.goto("/account?tab=settings");
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await page.goto("/learn/fastapi-payload-mismatch");
  await page.getByRole("region", { name: "Sign in to start this lesson" }).getByRole("link", { name: "Sign in", exact: true }).click();
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password", { exact: true }).fill("Controlled-fixture-password-47");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL(/\/learn\/fastapi-payload-mismatch$/);
  await expect(page.getByRole("button", { name: "Start lesson", exact: true })).toBeVisible();
});
