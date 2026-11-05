import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { CreateCustomLesson, YourLessons } from "@/components/learning/hub/private-guide-hub";
import { GuideReader } from "@/components/learning/guides/guide-reader";
import { ApiError } from "@/lib/api/client";
import { learningGuidesApi, type GuideDetail } from "@/lib/api/learning-guides";

const state = vi.hoisted(() => ({ auth: { status: "signed-in", userId: "synthetic-owner" } as { status: string; userId?: string }, getSession: vi.fn(), refreshSession: vi.fn() }));
vi.mock("@/lib/supabase/use-auth", () => ({ useAuth: () => state.auth }));
vi.mock("@/lib/supabase/browser", () => ({ browserAuth: () => ({ auth: { getSession: state.getSession, refreshSession: state.refreshSession } }) }));

const guide: GuideDetail = {
  id: "00000000-0000-4000-8000-000000000123", topic: "Python variables", status: "ready", created_at: "2026-11-03T10:00:00Z", updated_at: "2026-11-03T10:00:01Z", version: "1.0.0", title: "Naming Python values",
  generation_version: "private-guide-generator-v1", request: { topic: "Python variables", start_level: "beginner", target_level: "intermediate", practical: true }, content_sha256: "a".repeat(64), source: "test_fixture", ungraded: true, execution_status: "not_executed",
  content: { schema_version: "private-learning-guide-v1", title: "Naming Python values", description: "Practice names and values.", learning_objectives: ["Describe variable binding."], sections: [{ id: "names", title: "Bind a name", explanation: "Assignment binds a name to a value.", example: { language: "python", code: "score = 3\nprint(score)", explanation: "An unexecuted example." }, practice: "Bind a name to a number.", expected_outcome: "Explain the name and value separately." }], summary: "A name refers to a value." },
};

function hub(ui: React.ReactNode) {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  state.auth = { status: "signed-in", userId: "synthetic-owner" };
  state.getSession.mockResolvedValue({ data: { session: { access_token: "synthetic-test-token" } }, error: null });
  state.refreshSession.mockReset();
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

test("a signed-in learner creates a private guide with goals and sees its real saved resource", async () => {
  const create = vi.spyOn(learningGuidesApi, "create").mockResolvedValue(guide);
  const user = userEvent.setup();
  hub(<CreateCustomLesson />);
  await user.type(screen.getByLabelText("What do you want to learn?"), "Python variables");
  await user.type(screen.getByLabelText("Learning goals (optional)"), "Understand assignment");
  await user.type(screen.getByLabelText("Explanation preferences (optional)"), "Short examples");
  await user.selectOptions(screen.getByLabelText("Target level"), "advanced");
  await user.click(screen.getByRole("button", { name: "Create lesson" }));
  expect(await screen.findByText("Your lesson is ready.")).toBeVisible();
  expect(create.mock.calls[0][0]).toEqual({ topic: "Python variables", start_level: "beginner", target_level: "advanced", practical: true, goals: "Understand assignment", preferences: "Short examples" });
  expect(create.mock.calls[0][1]).toMatch(/^[0-9a-f-]{36}$/);
  expect(screen.getByRole("link", { name: "Open your lesson" })).toHaveAttribute("href", `/learn/guides/${guide.id}`);
  expect(screen.getByText("Test fixture content · This is not a live Gemini result.")).toBeVisible();
});

test("an uncertain create retains the exact idempotency key and does not fabricate a result", async () => {
  const create = vi.spyOn(learningGuidesApi, "create").mockRejectedValueOnce(new ApiError(0, "Timed out.", "client_timeout")).mockResolvedValueOnce(guide);
  const user = userEvent.setup();
  hub(<CreateCustomLesson />);
  await user.type(screen.getByLabelText("What do you want to learn?"), "Python variables");
  await user.click(screen.getByRole("button", { name: "Create lesson" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("same request");
  expect(screen.queryByRole("link", { name: "Open your lesson" })).toBeNull();
  await user.click(screen.getByRole("button", { name: "Create lesson" }));
  await screen.findByRole("link", { name: "Open your lesson" });
  expect(create.mock.calls[0][1]).toBe(create.mock.calls[1][1]);
  expect(create.mock.calls[0][0]).toEqual(create.mock.calls[1][0]);
});

test("unavailable generation and in-flight work remain honest and non-reentrant", async () => {
  let finish!: (value: GuideDetail) => void;
  const create = vi.spyOn(learningGuidesApi, "create").mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
  const user = userEvent.setup();
  hub(<CreateCustomLesson />);
  await user.type(screen.getByLabelText("What do you want to learn?"), "Python variables");
  await user.click(screen.getByRole("button", { name: "Create lesson" }));
  expect(screen.getByRole("button", { name: "Creating lesson…" })).toBeDisabled();
  expect(screen.getByText("Creating your lesson. It isn't ready yet.")).toBeVisible();
  finish({ ...guide, status: "unavailable", content: null, source: null });
  expect(await screen.findByText("No lesson was created this time.")).toBeVisible();
  expect(screen.getByText(/Nothing was published or graded\. Try again in a few minutes/)).toBeVisible();
  expect(screen.getByText("Support details")).toBeVisible();
  expect(screen.getByRole("link", { name: "Your request" })).toBeVisible();
  expect(screen.queryByRole("link", { name: "Open your lesson" })).toBeNull();
  expect(create).toHaveBeenCalledOnce();
});

test("guest, account change and credential-like input do not expose or submit a guide", async () => {
  const create = vi.spyOn(learningGuidesApi, "create");
  const list = vi.spyOn(learningGuidesApi, "list");
  state.auth = { status: "guest" };
  const user = userEvent.setup();
  const view = hub(<><YourLessons /><CreateCustomLesson /></>);
  await user.type(screen.getByLabelText("What do you want to learn?"), "Python variables");
  expect(screen.getByRole("button", { name: "Create lesson" })).toBeDisabled();
  expect(list).not.toHaveBeenCalled();
  expect(create).not.toHaveBeenCalled();
  view.unmount();
  state.auth = { status: "signed-in", userId: "synthetic-owner" };
  hub(<CreateCustomLesson />);
  await user.type(screen.getByLabelText("What do you want to learn?"), "api_key=synthetic-private-canary");
  expect(screen.getByRole("alert")).toHaveTextContent("Remove passwords");
  expect(screen.getByRole("button", { name: "Create lesson" })).toBeDisabled();
  expect(create).not.toHaveBeenCalled();
});

test("the saved guide reader labels unexecuted practice and never interprets generated HTML", async () => {
  const unsafe = structuredClone(guide);
  unsafe.content!.sections[0].example!.code = '<script>window.privateCanary = true</script>';
  vi.spyOn(learningGuidesApi, "get").mockResolvedValue(unsafe);
  const view = render(<GuideReader guideId={guide.id} />);
  expect(await screen.findByRole("heading", { name: "Naming Python values" })).toBeVisible();
  expect(screen.getByText(/Practice is ungraded and does not change/)).toBeVisible();
  expect(screen.getByText(/Suggested python example/)).toHaveTextContent("Not executed");
  expect(screen.getByText('<script>window.privateCanary = true</script>')).toBeVisible();
  expect(document.querySelector("script")).toBeNull();
  expect(screen.getByLabelText("Your private scratch notes (not saved or sent)")).toBeVisible();
  state.auth = { status: "guest" };
  view.rerender(<GuideReader guideId={guide.id} />);
  expect(screen.getByRole("heading", { name: "Sign in to open your lesson" })).toBeVisible();
  expect(screen.queryByRole("heading", { name: "Naming Python values" })).toBeNull();
});

test("foreign or missing guide errors reveal no saved content and offer only a safe retry", async () => {
  vi.spyOn(learningGuidesApi, "get").mockRejectedValue(new ApiError(404, "Not found."));
  render(<GuideReader guideId="foreign-or-missing" />);
  expect(await screen.findByRole("alert")).toHaveTextContent("unavailable or doesn't belong");
  expect(screen.queryByText("Naming Python values")).toBeNull();
  expect(screen.getByRole("button", { name: "Try opening again" })).toBeVisible();
});

test("list and read remain owner-scoped, and ready guides open without implying verified completion", async () => {
  const list = vi.spyOn(learningGuidesApi, "list").mockResolvedValue([guide]);
  const view = hub(<YourLessons />);
  expect(await screen.findByRole("link", { name: "Open lesson" })).toHaveAttribute("href", `/learn/guides/${guide.id}`);
  expect(screen.getByText("Version 1.0.0 · Ungraded practice")).toBeVisible();
  state.auth = { status: "signed-in", userId: "synthetic-other-owner" };
  list.mockResolvedValue([]);
  view.rerender(<QueryClientProvider client={new QueryClient()}><YourLessons /></QueryClientProvider>);
  await waitFor(() => expect(screen.queryByText("Naming Python values")).toBeNull());
});

test("guide writes use the protected API and are not automatically replayed on unauthorized results", async () => {
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://127.0.0.1:8000");
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { message: "Sign in again.", code: "unauthenticated" } }), { status: 401 }));
  vi.stubGlobal("fetch", fetch);
  await expect(learningGuidesApi.create(guide.request, guide.id)).rejects.toBeInstanceOf(ApiError);
  expect(fetch).toHaveBeenCalledOnce();
  const [url, init] = fetch.mock.calls[0];
  expect(url).toBe("http://127.0.0.1:8000/api/v1/learning-guides");
  expect(init.headers).toMatchObject({ Authorization: "Bearer synthetic-test-token", "Idempotency-Key": guide.id, "X-Trace-Client": "learning-web" });
  expect(state.refreshSession).not.toHaveBeenCalled();
});


test("waits for sign-in before accepting a draft that an owner remount would erase", async () => {
  state.auth = { status: "loading" };
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const tree = () => <QueryClientProvider client={client}><CreateCustomLesson /></QueryClientProvider>;
  const page = render(tree());
  expect(screen.getByLabelText("What do you want to learn?")).toBeDisabled();
  expect(screen.getByText("Checking your sign-in?")).toBeVisible();
  state.auth = { status: "signed-in", userId: "synthetic-owner" }; page.rerender(tree());
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("What do you want to learn?"), "Python variables");
  expect(screen.getByLabelText("What do you want to learn?")).toHaveValue("Python variables");
  expect(screen.getByRole("button", { name: "Create lesson" })).toBeEnabled();
});
