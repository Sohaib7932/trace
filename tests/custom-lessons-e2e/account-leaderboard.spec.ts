import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

// Account and leaderboard on the fixture stack (mock provider transport, no Gemini). The
// leaderboard has no backend endpoint yet, so this stack builds with the labelled demo adapter.
const AUTH = "http://127.0.0.1:8111";
const PASSWORD = "Controlled-fixture-password-47";

async function signUp(page: Page, request: APIRequestContext) {
  const email = `board-${crypto.randomUUID()}@example.test`;
  await page.goto("/sign-up");
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByLabel("Confirm password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Create account", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Check your inbox" })).toBeVisible();
  const { link } = await (await request.get(`${AUTH}/fixture/mail?email=${encodeURIComponent(email)}`)).json() as { link: string };
  await page.goto(link);
  await expect(page).toHaveURL(/\/account$/);
  return email;
}
const noOverflow = async (page: Page) => expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
const nav = (page: Page) => page.getByRole("navigation", { name: "Main" });

test("account: tabs, a created lesson in history and stats, avatar that persists after reload", async ({ page, request }) => {
  test.setTimeout(120_000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await signUp(page, request);
  await expect(page.getByRole("heading", { level: 1, name: "Trace learner" })).toBeVisible();

  // A lesson created elsewhere shows on /account without a manual refresh of the list code.
  await page.goto("/learn/new");
  await page.getByLabel("What do you want to learn?").fill("Teach me how FastAPI validates a request body, with predict-and-fix exercises.");
  await page.getByRole("button", { name: "Create lesson" }).click();
  await expect(page.getByRole("heading", { name: "Your lesson is ready" })).toBeVisible({ timeout: 20_000 });

  // Navbar to Account (the Account link is in the bar on every width).
  await nav(page).getByRole("link", { name: "Account" }).click();
  await expect(page).toHaveURL(/\/account/);
  const stats = page.getByRole("heading", { name: "Your numbers" }).locator("xpath=ancestor::section[1]");
  await expect(stats).toContainText("1Lessons created");
  // No Trace lesson started yet: the account has no learner, so Trace stats stay hidden (reading them would create one).
  await expect(stats).not.toContainText("Trace lessons completed");

  const tabs = page.getByRole("tablist", { name: "Account" });
  await tabs.getByRole("tab", { name: "Learning history" }).click();
  await expect(page).toHaveURL(/tab=history$/);
  const mine = page.getByRole("heading", { name: "My lessons" }).locator("xpath=ancestor::section[1]");
  await expect(mine.getByRole("article").first()).toContainText("Reading code carefully");
  await expect(mine).not.toContainText(/verified by the server/i);

  // Keyboard: arrow keys move between tabs.
  await tabs.getByRole("tab", { name: "Learning history" }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(tabs.getByRole("tab", { name: "Settings" })).toHaveAttribute("aria-selected", "true");
  await expect(page).toHaveURL(/tab=settings$/);
  await expect(page.getByText("For support")).toBeVisible();

  // Avatar: choose, save, and it is still there after a reload (account or this device).
  await tabs.getByRole("tab", { name: "Overview" }).click();
  await page.getByRole("button", { name: "Change avatar" }).click();
  const dialog = page.getByRole("dialog", { name: "Choose your avatar" });
  await dialog.getByRole("button", { name: "Coral planet" }).click();
  await dialog.getByRole("button", { name: "Save avatar" }).click();
  await expect(dialog.getByText(/^Saved/)).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(page.getByRole("button", { name: "Change avatar" })).toBeFocused();
  await page.reload();
  await expect(page.locator("header svg[data-avatar]").first()).toHaveAttribute("data-avatar", "planet-coral");
  await noOverflow(page);
  expect(errors).toEqual([]);
});

test("account: deleting a lesson on My lessons updates the account page", async ({ page, request }) => {
  test.setTimeout(120_000);
  await signUp(page, request);
  await page.goto("/learn/new");
  await page.getByLabel("What do you want to learn?").fill("Explain JavaScript closures with small examples to predict.");
  await page.getByRole("button", { name: "Create lesson" }).click();
  await expect(page.getByRole("heading", { name: "Your lesson is ready" })).toBeVisible({ timeout: 20_000 });
  await page.goto("/learn/my");
  const card = page.getByRole("article").first();
  await card.getByRole("button", { name: /^More actions for/ }).click();
  await card.getByRole("button", { name: "Delete", exact: true }).click();
  await page.getByRole("dialog", { name: "Delete this lesson?" }).getByRole("button", { name: "Delete", exact: true }).click();
  await expect(page.getByRole("heading", { name: "No lessons yet" })).toBeVisible();
  await page.goto("/account?tab=history");
  const mine = page.getByRole("heading", { name: "My lessons" }).locator("xpath=ancestor::section[1]");
  await expect(mine.getByText("You haven't created a lesson yet.")).toBeVisible();
});

test("leaderboard: signed-out teaser, demo board with many ties, load more, jump to my position, keyboard path", async ({ page, request, isMobile }) => {
  test.setTimeout(120_000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));

  // Signed out: a teaser and one Sign in button, no board.
  await page.goto("/leaderboard");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Leaderboard");
  await expect(page.getByRole("heading", { name: "Sign in to see the leaderboard" })).toBeVisible();
  await expect(page.locator("li.lb-row")).toHaveCount(0);
  await noOverflow(page);

  await signUp(page, request);
  if (isMobile) await page.getByRole("button", { name: "Open menu" }).click();
  await (isMobile ? page.locator("#mobile-menu") : nav(page)).getByRole("link", { name: "Leaderboard" }).click();
  await expect(page).toHaveURL(/\/leaderboard$/);
  await expect(page.getByRole("main").getByText("Demo data · fictional people, not real results")).toBeVisible();
  await expect(page.getByText(/Updated \d+ minutes? ago/)).toBeVisible();

  // Many ties: nine people share rank 1, so the top shows highlighted rows rather than a podium.
  await expect(page.locator("li.lb-row")).toHaveCount(20);
  await expect(page.getByLabel("Rank 1, tied").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Jump to my position" })).toHaveCount(0);

  // I am on page two: load more, then jump to my row.
  await page.getByRole("button", { name: "Load more" }).click();
  await expect(page.locator("li.lb-row")).toHaveCount(40);
  const jump = page.getByRole("button", { name: "Jump to my position" });
  await jump.focus();
  await page.keyboard.press("Enter");
  const mine = page.locator("li.lb-row[data-me]");
  await expect(mine).toBeFocused();
  await expect(mine.getByText("You", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Your position" }).locator("xpath=ancestor::section[1]")).toContainText("verified problem");

  // The board never offers sorting or a score field.
  await expect(page.getByRole("combobox")).toHaveCount(0);
  await expect(page.getByRole("main")).not.toContainText(/\bXP\b|streak|points?\b/i);
  await page.getByRole("button", { name: "Load more" }).click();
  await expect(page.locator("li.lb-row")).toHaveCount(60);
  await page.getByRole("button", { name: "Load more" }).click();
  await expect(page.locator("li.lb-row")).toHaveCount(64);
  await expect(page.getByRole("button", { name: "Load more" })).toHaveCount(0);
  await noOverflow(page);
  expect(errors).toEqual([]);
});
