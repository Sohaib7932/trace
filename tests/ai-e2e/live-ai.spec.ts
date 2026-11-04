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
  return email;
}

async function prepareFixtureProject(email: string, request: APIRequestContext) {
  // Real loopback auth/JWT and owned SQL records; only GitHub/AI providers are fixtures.
  const login = await request.post("http://127.0.0.1:8101/auth/v1/token?grant_type=password", {
    data: { email, password: "Controlled-browser-fixture-47" },
    timeout: 10_000,
  });
  expect(login.status()).toBe(200);
  const token = (await login.json()).access_token as string;
  const headers = { Authorization: `Bearer ${token}`, Origin: "http://127.0.0.1:3200", "X-Trace-Client": "learning-web" };
  const prepared = await request.post(`${API}/__fixture__/github/connect`, { headers, timeout: 10_000 });
  expect(prepared.status()).toBe(200);
  const project = await prepared.json() as { connection_id: string; commit_sha: string; source: string; live_github_authorization: boolean };
  expect(project.source).toBe("test_fixture");
  expect(project.live_github_authorization).toBe(false);
  return { ...project, headers };
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
  const followUpResponse = page.waitForResponse((r) => r.url().endsWith("/support/ask") && r.request().method() === "POST");
  await help.getByLabel("Your question").fill("When is that due?");
  await help.getByRole("button", { name: "Send question" }).click();
  const followUp = await followUpResponse;
  expect(followUp.status()).toBe(200);
  expect(followUp.request().postDataJSON()).toMatchObject({
    question: "When is that due?",
    history: [
      { role: "user", text: "When are review checkpoints due?" },
      { role: "assistant", text: expect.any(String) },
    ],
  });
  expect((await followUp.json()).status).toBe("answered");
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

test("conversational tutor sends natural questions and bounded follow-up history without claiming execution", async ({ page, request }) => {
  test.setTimeout(120_000);
  await signUp(page, request);
  await page.goto("/learn/fastapi-payload-mismatch");
  await page.getByRole("button", { name: "Start lesson", exact: true }).click();
  await expect(page.getByLabel("The request will be rejected", { exact: true })).toBeVisible();
  if (await page.locator(".tutor-bar").isVisible()) await page.locator(".tutor-bar button").click();
  const drawer = page.getByRole("dialog", { name: "Lesson tutor", exact: true });
  const panel = await drawer.isVisible() ? drawer : page.getByRole("complementary", { name: "Lesson tutor", exact: true });
  await panel.getByLabel("Explanation style").selectOption("direct");
  await panel.getByLabel("Ask about this lesson").fill("How is an API schema different from a database schema?");
  const firstResponse = page.waitForResponse((r) => r.url().endsWith("/tutor/ask") && r.request().method() === "POST");
  await panel.getByRole("button", { name: "Ask", exact: true }).click();
  const first = await firstResponse;
  expect(first.status()).toBe(200);
  expect(first.request().postDataJSON()).toMatchObject({ mode: "conversation", style: "direct", code: null, history: [] });
  expect(await first.json()).toMatchObject({ source: "test_fixture", execution_status: "not_executed", history_scope: "client_page_session" });
  await expect(panel.locator(".tutor-reply")).toContainText("Test fixture guidance");
  await panel.getByLabel("Ask about this lesson").fill("Can you explain that comparison in another way?");
  const followupResponse = page.waitForResponse((r) => r.url().endsWith("/tutor/ask") && r.request().method() === "POST");
  await panel.getByRole("button", { name: "Ask", exact: true }).click();
  const followup = await followupResponse;
  expect(followup.status()).toBe(200);
  const body = followup.request().postDataJSON();
  expect(body.history).toHaveLength(2);
  expect(body.history.map((entry: { role: string }) => entry.role)).toEqual(["user", "assistant"]);
  expect(body.code).toBeNull();
  expect(Object.keys(body).sort()).toEqual(["code", "history", "mode", "question", "style"]);
  await expect(panel.getByRole("button", { name: "Clear conversation" })).toBeVisible();
  await panel.getByRole("button", { name: "Clear conversation" }).click();
  await expect(panel.locator(".tutor-reply")).toHaveCount(0);
  // This is the real HTTP adapter with explicit fixture provenance, never a Gemini live test.
});

test("private guide generation persists an owned readable guide and never becomes verified lesson progress", async ({ page, request }, testInfo) => {
  test.setTimeout(120_000);
  await signUp(page, request);
  await page.goto("/learn");
  await page.getByLabel("What do you want to learn?").fill("Python variables");
  await page.getByLabel("Learning goals (optional)").fill("Explain assignment clearly");
  await page.getByLabel("Explanation preferences (optional)").fill("Short examples");
  const verificationCalls: string[] = [];
  page.on("request", (r) => { if (/\/attempts\/[^/]+\/verify/.test(r.url())) verificationCalls.push(r.url()); });
  const createdResponse = page.waitForResponse((r) => r.url().endsWith("/learning-guides") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Create guide", exact: true }).click();
  const created = await createdResponse;
  expect(created.status()).toBe(201);
  expect(created.headers()["cache-control"]).toBe("no-store");
  expect(created.request().headers()["idempotency-key"]).toMatch(/^[0-9a-f-]{36}$/);
  const saved = await created.json();
  expect(saved).toMatchObject({ status: "ready", source: "test_fixture", ungraded: true, execution_status: "not_executed" });
  expect(saved.content.schema_version).toBe("private-learning-guide-v1");
  await expect(page.getByRole("region", { name: "Create a private learning guide" }).getByText("Test fixture content · This is not a live Gemini result.")).toBeVisible();
  await page.getByRole("link", { name: "Open your guide", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/learn/guides/${saved.id}$`));
  await expect(page.getByRole("heading", { name: saved.content.title, exact: true })).toBeVisible();
  await expect(page.getByRole("complementary", { name: "Guide limitations" })).toContainText("Practice is ungraded");
  await expect(page.getByRole("complementary", { name: "Guide limitations" }).getByText("Test fixture content · This is not a live Gemini result.")).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: saved.content.title, exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("private-guide-reader.png"), fullPage: true });
  await page.getByRole("link", { name: "Back to your lessons", exact: true }).click();
  await expect(page.getByRole("link", { name: "Open guide", exact: true })).toHaveAttribute("href", `/learn/guides/${saved.id}`);
  expect(verificationCalls).toEqual([]);
  // Another actual fixture account cannot open this resource, even knowing its URL.
  await page.context().clearCookies();
  await signUp(page, request);
  await page.goto(`/learn/guides/${saved.id}`);
  await expect(page.getByRole("main").getByRole("alert")).toContainText("unavailable or does not belong");
  await expect(page.getByRole("heading", { name: saved.content.title, exact: true })).toHaveCount(0);
});

test("a guide provider timeout persists only an unavailable request and never invents a guide", async ({ page, request }) => {
  test.setTimeout(120_000);
  await signUp(page, request);
  await request.post(`${API}/__fixture__/ai-outcome/timeout`);
  await page.goto("/learn");
  await page.getByLabel("What do you want to learn?").fill("Python variables");
  const createdResponse = page.waitForResponse((r) => r.url().endsWith("/learning-guides") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Create guide", exact: true }).click();
  const created = await createdResponse;
  expect(created.status()).toBe(201);
  expect(await created.json()).toMatchObject({ status: "unavailable", content: null });
  await expect(page.getByText("Gemini could not create a valid guide. No lesson was completed or published.")).toBeVisible();
  await expect(page.getByRole("link", { name: "Open your guide" })).toHaveCount(0);
  await page.getByRole("link", { name: "View saved request", exact: true }).click();
  await expect(page.getByRole("heading", { name: "This guide is unavailable" })).toBeVisible();
});

test("fixture repository questions use exact cited sources and bounded follow-ups", async ({ page, request }, testInfo) => {
  test.setTimeout(60_000);
  page.setDefaultTimeout(10_000);
  const email = await signUp(page, request);
  const prepared = await prepareFixtureProject(email, request);
  await page.goto("/projects");
  await expect(page.getByRole("combobox", { name: "Repository", exact: true })).toBeVisible();
  await page.getByRole("combobox", { name: "Repository", exact: true }).selectOption(prepared.connection_id);
  await page.getByLabel("Exact commit SHA", { exact: true }).fill(prepared.commit_sha);
  const ingestResponse = page.waitForResponse((r) => r.url().endsWith("/ingest") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Read repository for questions", exact: true }).click();
  const ingested = await ingestResponse;
  expect(ingested.status()).toBe(200);
  expect(ingested.headers()["cache-control"]).toBe("no-store");
  const knowledge = await ingested.json();
  expect(knowledge.schema_version).toBe("project-repository-v2");
  expect(knowledge.complete_repository).toBe(false);
  await expect(page.getByRole("heading", { name: "Repository knowledge", exact: true })).toBeVisible();
  const question = "Teach me how authentication works in this project.";
  await page.getByLabel("Ask about this project", { exact: true }).fill(question);
  const answerResponse = page.waitForResponse((r) => r.url().endsWith("/ask") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Ask grounded question", exact: true }).click();
  const answer = await answerResponse;
  expect(answer.status()).toBe(200);
  expect(answer.headers()["cache-control"]).toBe("no-store");
  const content = await answer.json();
  expect(content).toMatchObject({ status: "answered", source: "test_fixture", grading: "ungraded", execution_status: "not_executed", can_complete_lesson: false });
  expect(content.sections[0].citations[0]).toMatchObject({ path: "backend/identity.py", line_start: 2, line_end: 2, quote: "return subject" });
  const first = page.getByRole("article").filter({ has: page.getByRole("heading", { name: question, exact: true }) });
  await expect(first.getByText("Test fixture · Ungraded · Not executed", { exact: true })).toBeVisible();
  await expect(first.getByText("backend/identity.py:2–2", { exact: true })).toBeVisible();
  await expect(first.getByText("return subject", { exact: true })).toBeVisible();
  await page.getByLabel("Ask about this project", { exact: true }).fill("Explain that return value.");
  const followUpResponse = page.waitForResponse((r) => r.url().endsWith("/ask") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Ask grounded question", exact: true }).click();
  const followUp = await followUpResponse;
  expect((await followUp.json()).status).toBe("answered");
  expect(followUp.request().postDataJSON().history.map((item: { role: string }) => item.role)).toEqual(["user", "assistant"]);
  await page.getByLabel("Ask about this project", { exact: true }).fill("Forecast Jupiter weather.");
  await page.getByRole("button", { name: "Ask grounded question", exact: true }).click();
  await expect(page.getByText("The ingested sources do not provide enough information for this question.", { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("project-question-fixture.png"), fullPage: true });
});

test("fixture repository disconnect withholds owned and foreign source access", async ({ page, request }) => {
  test.setTimeout(60_000);
  page.setDefaultTimeout(10_000);
  // This independent owner keeps authorization checks separate from the longer question journey.
  const email = await signUp(page, request);
  const prepared = await prepareFixtureProject(email, request);
  await page.goto("/projects");
  await expect(page.getByRole("combobox", { name: "Repository", exact: true })).toBeVisible();
  await page.getByRole("combobox", { name: "Repository", exact: true }).selectOption(prepared.connection_id);
  await page.getByLabel("Exact commit SHA", { exact: true }).fill(prepared.commit_sha);
  const ingestResponse = page.waitForResponse((r) => r.url().endsWith("/ingest") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Read repository for questions", exact: true }).click();
  expect((await ingestResponse).status()).toBe(200);
  await expect(page.getByRole("heading", { name: "Repository knowledge", exact: true })).toBeVisible();
  await page.getByLabel("Ask about this project", { exact: true }).fill("Teach me how authentication works in this project.");
  const answerResponse = page.waitForResponse((r) => r.url().endsWith("/ask") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Ask grounded question", exact: true }).click();
  const answer = await answerResponse;
  expect(answer.status()).toBe(200);
  expect(await answer.json()).toMatchObject({ status: "answered", source: "test_fixture" });
  await expect(page.getByText("Test fixture · Ungraded · Not executed", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Connect GitHub App", exact: true })).toBeEnabled();
  await page.getByRole("button", { name: "Disconnect this repository from Trace", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Repository knowledge", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Ask grounded question", exact: true })).toHaveCount(0);
  // Content clears before the awaited connection refresh; wait for the complete UI operation.
  await expect(page.getByRole("button", { name: "Connect GitHub App", exact: true })).toBeEnabled();
  await expect(page.getByText("Working… This may return unavailable.", { exact: true })).toHaveCount(0);
  const knowledgePath = `/api/v1/projects/github/repositories/${prepared.connection_id}/knowledge?commit_sha=${prepared.commit_sha}`;
  const withheld = await request.get(`${API}${knowledgePath}`, { headers: prepared.headers, timeout: 10_000 });
  const withheldBody = await withheld.json();
  const safeErrorCode = typeof withheldBody.error?.code === "string" ? withheldBody.error.code.replace(/[^a-zA-Z0-9_-]/g, "").slice(0, 64) : "unspecified";
  expect(withheld.status(), `Owned knowledge read after disconnect: HTTP ${withheld.status()}, code ${safeErrorCode}`).toBe(404);
  await page.context().clearCookies();
  const otherEmail = await signUp(page, request);
  const otherLogin = await request.post("http://127.0.0.1:8101/auth/v1/token?grant_type=password", { data: { email: otherEmail, password: "Controlled-browser-fixture-47" }, timeout: 10_000 });
  const otherToken = (await otherLogin.json()).access_token;
  const foreign = await request.get(`${API}${knowledgePath}`, { headers: { ...prepared.headers, Authorization: `Bearer ${otherToken}` }, timeout: 10_000 });
  expect(foreign.status()).toBe(404);
  await page.goto("/projects");
  await expect(page.getByText("No repositories connected.", { exact: true })).toBeVisible();
});

test("repository provider timeout has no invented answer or source citations", async ({ page, request }) => {
  test.setTimeout(60_000);
  page.setDefaultTimeout(10_000);
  const email = await signUp(page, request);
  const prepared = await prepareFixtureProject(email, request);
  await page.goto("/projects");
  await expect(page.getByRole("combobox", { name: "Repository", exact: true })).toBeVisible();
  await page.getByRole("combobox", { name: "Repository", exact: true }).selectOption(prepared.connection_id);
  await page.getByLabel("Exact commit SHA", { exact: true }).fill(prepared.commit_sha);
  await page.getByRole("button", { name: "Read repository for questions", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Repository knowledge", exact: true })).toBeVisible();
  await request.post(`${API}/__fixture__/ai-outcome/timeout`);
  await page.getByLabel("Ask about this project", { exact: true }).fill("Explain authentication");
  const result = page.waitForResponse((r) => r.url().endsWith("/ask") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Ask grounded question", exact: true }).click();
  expect(await (await result).json()).toMatchObject({ status: "unavailable", source: "none", sections: [] });
  await expect(page.getByText("Gemini could not return a validated grounded answer. No answer was invented.", { exact: true })).toBeVisible();
  await expect(page.getByText("Test fixture · Ungraded · Not executed", { exact: true })).toHaveCount(0);
});
