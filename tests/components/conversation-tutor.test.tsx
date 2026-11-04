import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { createAiClients } from "@/lib/ai/client";
import { ApiError } from "@/lib/api/client";
import { TutorPanel } from "@/components/learning/tutor/tutor-panel";
import { savedProgress } from "../fixtures/learning";

const auth = vi.hoisted(() => ({ getSession: vi.fn(), refreshSession: vi.fn() }));
vi.mock("@/lib/supabase/browser", () => ({ browserAuth: () => ({ auth }) }));
vi.mock("@/lib/supabase/use-auth", () => ({ useAuth: () => ({ status: "signed-in", email: null, userId: "synthetic-ui-user" }) }));

const context = { lessonId: "fastapi-payload-mismatch" as const, stage: "predicting" as const, sessionId: "owned-session" };
const reply = {
  mode: "conversation", status: "answered", source: "ai", text: "An await can suspend a coroutine. This example has not been executed.",
  interpretation_only: true, can_complete_lesson: false, execution_status: "not_executed", history_scope: "client_page_session",
};

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_AI_MODE", "real");
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://127.0.0.1:8000");
  auth.getSession.mockResolvedValue({ data: { session: { access_token: "controlled-fixture-token" } }, error: null });
  auth.refreshSession.mockResolvedValue({ data: { session: { access_token: "new-fixture-token" } }, error: null });
  vi.stubGlobal("matchMedia", () => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
  localStorage.clear();
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.unstubAllEnvs(); auth.refreshSession.mockClear(); });

test("conversation uses the existing owned endpoint and separates dialogue from client evidence", async () => {
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(reply)));
  vi.stubGlobal("fetch", fetch);
  const answer = await createAiClients("real").tutor.converse!({
    ...context, code: "async def example(): return 1", style: "direct",
    latestRun: { id: "client-claim", status: "passed" }, hintsUsed: 99,
    history: [{ role: "user", text: "What does async mean?" }],
  }, "Why do I need await?");
  expect(answer).toEqual(reply);
  const [url, request] = fetch.mock.calls[0];
  expect(url).toContain("/sessions/owned-session/tutor/ask");
  expect(JSON.parse(request.body)).toEqual({
    mode: "conversation", question: "Why do I need await?", style: "direct",
    code: "async def example(): return 1", history: [{ role: "user", text: "What does async mean?" }],
  });
  expect(request.body).not.toContain("client-claim");
  expect(request.body).not.toContain("hintsUsed");
});

test("AI requests are not automatically replayed after a post-provider 401", async () => {
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { message: "Sign in again." } }), { status: 401 }));
  vi.stubGlobal("fetch", fetch);
  await expect(createAiClients("real").tutor.converse!(context, "Explain await.")).rejects.toBeInstanceOf(ApiError);
  expect(fetch).toHaveBeenCalledOnce();
  expect(auth.refreshSession).not.toHaveBeenCalled();
});

test("oldest dialogue is dropped to fit the context bound; current code is never silently truncated", async () => {
  const fetch = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify(reply))));
  vi.stubGlobal("fetch", fetch);
  await createAiClients("real").tutor.converse!({ ...context, code: "c".repeat(6000), history: Array.from({ length: 6 }, () => ({ role: "user" as const, text: "h".repeat(1600) })) }, "Explain this.");
  const body = JSON.parse(fetch.mock.calls[0][1].body);
  expect(new TextEncoder().encode(fetch.mock.calls[0][1].body).length).toBeLessThanOrEqual(10000);
  expect(body.history.length).toBeLessThan(6);
  expect(body.code).toHaveLength(6000);
  await expect(createAiClients("real").tutor.converse!({ ...context, code: "界".repeat(6000) }, "Explain this.")).rejects.toMatchObject({ code: "context_limit" });
  expect(fetch).toHaveBeenCalledOnce();
});

test("manual cancellation reaches fetch and returns a safe stopped state", async () => {
  let entered!: () => void;
  const started = new Promise<void>((resolve) => { entered = resolve; });
  const fetch = vi.fn((_url, options: RequestInit) => new Promise<Response>((_resolve, reject) => {
    options.signal!.addEventListener("abort", () => reject(new DOMException("Stopped", "AbortError")), { once: true });
    entered();
  }));
  vi.stubGlobal("fetch", fetch);
  const controller = new AbortController();
  const pending = createAiClients("real").tutor.converse!(context, "Explain await.", { signal: controller.signal });
  await started;
  controller.abort();
  await expect(pending).rejects.toMatchObject({ code: "request_cancelled" });
  expect(fetch).toHaveBeenCalledOnce();
});

test("real panel supports follow-up history, direct style and session-scoped clearing", async () => {
  const user = userEvent.setup();
  const fetch = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify(reply))));
  vi.stubGlobal("fetch", fetch);
  const props = { lessonId: context.lessonId, lessonTitle: "Follow the note", progress: savedProgress, hint: { request: vi.fn(), pending: false, available: false } };
  const view = render(<TutorPanel {...props} />);
  await user.click(screen.getByRole("button", { name: /Lesson tutor/ }));
  const panel = screen.getByRole("dialog", { name: "Lesson tutor" });
  await user.selectOptions(within(panel).getByLabelText("Explanation style"), "direct");
  await user.type(within(panel).getByLabelText("Ask about this lesson"), "How does await work?");
  await user.click(within(panel).getByRole("button", { name: /^Ask$/ }));
  await waitFor(() => expect(panel.querySelector(".tutor-reply")).toHaveTextContent("coroutine"));
  await user.type(within(panel).getByLabelText("Ask about this lesson"), "How about a follow-up example?");
  await user.click(within(panel).getByRole("button", { name: /^Ask$/ }));
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
  const body = JSON.parse(fetch.mock.calls[1][1].body);
  expect(body.mode).toBe("conversation");
  expect(body.style).toBe("direct");
  expect(body.history).toEqual([{ role: "user", text: "How does await work?" }, { role: "assistant", text: reply.text }]);
  view.rerender(<TutorPanel {...props} progress={{ ...savedProgress, session: { ...savedProgress.session, id: "another-owned-session" } }} />);
  expect(screen.queryByRole("button", { name: "Clear conversation" })).toBeNull();
});
