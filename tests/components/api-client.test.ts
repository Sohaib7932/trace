import { afterEach, expect, test, vi } from "vitest";
import { ApiError, learningApi } from "@/lib/api/client";

afterEach(() => vi.unstubAllGlobals());

test("API requests include cookies, the client header and the stable retry key", async () => {
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: "attempt-fixture" }), { status: 201 }));
  vi.stubGlobal("fetch", fetch);
  await learningApi.attempt("session", { change_type: "rename_payload_field", field_name: "body", explanation: "" }, "stable-key");
  expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/api/v1/sessions/session/attempts"), expect.objectContaining({ credentials: "include", method: "POST", headers: expect.objectContaining({ "X-Trace-Client": "learning-web", "Idempotency-Key": "stable-key" }) }));
});

test("missing identity is created, but a dependency failure does not create another learner", async () => {
  const fetch = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ error: { message: "Missing credential" } }), { status: 401 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ learner_id: "fixture", expires_at: "later" })));
  vi.stubGlobal("fetch", fetch);
  await expect(learningApi.identity()).resolves.toHaveProperty("learner_id", "fixture");
  fetch.mockReset().mockResolvedValue(new Response(JSON.stringify({ error: { message: "Database unavailable" } }), { status: 503 }));
  await expect(learningApi.identity()).rejects.toThrow("Database unavailable");
  expect(fetch).toHaveBeenCalledTimes(1);
});

test("network failures remain errors instead of invented successful progress", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
  await expect(learningApi.progress("session")).rejects.toBeInstanceOf(ApiError);
});

test("returning identities use protected bootstrap so the server can renew near-expiry cookies", async () => {
  const identity = { learner_id: "fixture", expires_at: "2026-12-01T00:00:00Z" };
  const fetch = vi.fn().mockImplementation(async () => new Response(JSON.stringify(identity)));
  vi.stubGlobal("fetch", fetch);
  await expect(learningApi.identity()).resolves.toEqual(identity);
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(fetch.mock.calls[1][0]).toContain("/learners/anonymous");
  expect(fetch.mock.calls[1][1]).toMatchObject({ method: "POST", credentials: "include", headers: { "X-Trace-Client": "learning-web" } });
});
