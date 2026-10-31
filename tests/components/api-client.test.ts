import { afterEach, expect, test, vi } from "vitest";
import { ApiError, learningApi } from "@/lib/api/client";
import { browserAuth } from "@/lib/supabase/browser";

vi.mock("@/lib/supabase/browser", () => ({ browserAuth: vi.fn(() => null) }));

afterEach(() => { vi.unstubAllGlobals(); vi.mocked(browserAuth).mockReset().mockReturnValue(null); });

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

test("all authenticated API operations use the current SDK access token centrally", async () => {
  const getSession = vi.fn().mockResolvedValue({ data: { session: { access_token: "controlled-test-token" } }, error: null });
  vi.mocked(browserAuth).mockReturnValue({ auth: { getSession } } as unknown as NonNullable<ReturnType<typeof browserAuth>>);
  const fetch = vi.fn().mockResolvedValue(new Response("{}")); vi.stubGlobal("fetch", fetch);
  await learningApi.lesson("fixture");
  expect(getSession).toHaveBeenCalledOnce();
  expect(fetch).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({ headers: expect.objectContaining({ Authorization: "Bearer controlled-test-token" }) }));
});

test("SDK refresh failures never fall back to anonymous requests", async () => {
  vi.mocked(browserAuth).mockReturnValue({ auth: { getSession: vi.fn().mockResolvedValue({ data: { session: null }, error: {} }) } } as unknown as NonNullable<ReturnType<typeof browserAuth>>);
  const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
  await expect(learningApi.identity()).rejects.toThrow("could not be refreshed");
  expect(fetch).not.toHaveBeenCalled();
});

test("a thrown SDK refresh error also fails closed with a safe message", async () => {
  vi.mocked(browserAuth).mockReturnValue({ auth: { getSession: vi.fn().mockRejectedValue(new Error("private SDK details")) } } as unknown as NonNullable<ReturnType<typeof browserAuth>>);
  const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
  await expect(learningApi.identity()).rejects.toThrow("could not be refreshed");
  expect(fetch).not.toHaveBeenCalled();
});
