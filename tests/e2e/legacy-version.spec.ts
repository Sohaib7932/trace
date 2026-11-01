import { expect, test } from "@playwright/test";

test.use({ trace: "off" });

test("catalog changes cannot replace an old session's pinned content or saved evidence", async ({ page }) => {
  test.setTimeout(90_000);
  const api = "http://127.0.0.1:8000";
  await page.route("**/api/v1/**", (route) => new URL(route.request().url()).origin === api ? route.continue() : route.abort("blockedbyclient"));
  await page.goto("/learn/fastapi-payload-mismatch");
  await expect(page.getByRole("button", { name: "Start lesson", exact: true })).toBeVisible();
  const legacyResponse = await page.request.get(`${api}/api/v1/lessons/fastapi-payload-mismatch?version=1.0.0`);
  expect(legacyResponse.status()).toBe(200);
  const legacy = await legacyResponse.json();
  const sessionResponse = await page.request.post(`${api}/api/v1/sessions`, {
    data: { lesson_id: legacy.id, version: "1.0.0" },
    headers: { Origin: "http://127.0.0.1:3100", "X-Trace-Client": "learning-web", "Idempotency-Key": crypto.randomUUID() },
  });
  expect(sessionResponse.status()).toBe(201);
  const session = await sessionResponse.json();
  await page.evaluate(({ lessonId, sessionId }) => localStorage.setItem(`trace.session.${lessonId}`, sessionId), { lessonId: legacy.id, sessionId: session.id });
  await page.reload();
  await page.getByLabel("The request will be rejected", { exact: true }).check();
  const reasoning = "This original prediction must survive a newer catalog publication.";
  await page.getByLabel("Why do you expect that?").fill(reasoning);
  await page.getByRole("button", { name: "Lock prediction", exact: true }).click();
  await page.getByRole("radio", { name: "body", exact: true }).check();
  await page.getByRole("button", { name: "Check my change", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Request rejected", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Request a hint", exact: true }).click();
  await expect(page.getByText("Hint 1 · fixture guidance", { exact: true })).toBeVisible();
  await page.getByRole("radio", { name: "content", exact: true }).check();
  await page.getByRole("button", { name: "Check my change", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Session complete", exact: true })).toBeVisible();
  const saved = await (await page.request.get(`${api}/api/v1/sessions/${session.id}/progress`)).json();
  try {
    const changed = await page.request.post(`${api}/__fixture__/catalog/advance`);
    expect(changed.status()).toBe(200);
    const future = await changed.json();
    expect(future.version_id).not.toBe(legacy.version_id);
    expect(future.version).not.toBe("1.0.0");
    expect((await (await page.request.get(`${api}/api/v1/lessons/${legacy.id}`)).json()).version_id).toBe(future.version_id);

    await page.reload();
    await expect(page.getByRole("heading", { level: 1, name: legacy.title, exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: future.title, exact: true })).toHaveCount(0);
    await expect(page.getByRole("region", { name: "Locked prediction" })).toContainText(reasoning);
    await expect(page.getByRole("heading", { name: "Attempt 1 · body", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Attempt 2 · content", exact: true })).toBeVisible();
    await expect(page.getByText("Hint 1 · fixture guidance", { exact: true })).toBeVisible();
    const passed = page.getByRole("region", { name: "Verification evidence, attempt 2" });
    await expect(passed.getByText("201", { exact: true })).toBeVisible();
    await expect(passed.getByText("1", { exact: true })).toBeVisible();
    expect(await (await page.request.get(`${api}/api/v1/sessions/${session.id}/progress`)).json()).toEqual(saved);
    expect(saved.session.lesson_version_id).toBe(legacy.version_id);
    expect(saved.lesson.version).toBe("1.0.0");
  } finally {
    const restored = await page.request.post(`${api}/__fixture__/catalog/restore`);
    expect(restored.status()).toBe(200);
    const baselineCopy = await restored.json();
    expect(baselineCopy.title).toBe(legacy.title);
    expect(baselineCopy.version_id).not.toBe(legacy.version_id);
    const latest = await (await page.request.get(`${api}/api/v1/lessons/${legacy.id}`)).json();
    expect(latest.version_id).toBe(baselineCopy.version_id);
    expect(latest.title).toBe(legacy.title);
  }
});
