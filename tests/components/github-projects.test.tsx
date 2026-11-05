import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StrictMode } from "react";
import { focusManager } from "@tanstack/react-query";
import { ConnectView } from "@/components/projects/connect";
import { ProjectTutor } from "@/components/projects/project-tutor";
import { ProjectView } from "@/components/projects/project-view";
import { ProjectsProviders } from "@/components/projects/shell";
import { githubQueue } from "@/lib/projects/queue";
import { GitHubProjects } from "@/components/projects/github-projects";
import { ApiError } from "@/lib/api/client";
import { clearGitHubAuthorization, githubAuthorizationUrl, pendingGitHubAuthorization, saveGitHubAuthorization, type ProjectAnswer, type RepositoryKnowledge } from "@/lib/api/github-projects";
import { safeNext } from "@/lib/auth/next-path";
import config from "../../next.config";

const mocks = vi.hoisted(() => ({ auth: { status: "guest" } as { status: string; userId?: string }, request: vi.fn() }));
vi.mock("@/lib/supabase/use-auth", () => ({ useAuth: () => mocks.auth }));
vi.mock("@/lib/api/client", async (original) => ({ ...await original<typeof import("@/lib/api/client")>(), protectedApiRequest: mocks.request }));
afterEach(() => { cleanup(); focusManager.setFocused(undefined); clearGitHubAuthorization(); });
beforeEach(() => { mocks.auth = { status: "guest" }; mocks.request.mockReset(); });
function page() { return render(<GitHubProjects />); }

describe("GitHub Project Learning boundary", () => {
  it("excludes callback queries from development request logs", () => {
    const logging = config.logging;
    const incoming = logging && logging.incomingRequests;
    expect(typeof incoming === "object" && incoming.ignore?.some((pattern) => pattern.test("/projects/github/callback?code=synthetic-code&state=synthetic-state"))).toBe(true);
  });
  it("allows the new owned screens as sign-in destinations without allowing callbacks or external redirects", () => {
    expect(safeNext("/projects")).toBe("/projects");
    expect(safeNext("/learn/guides/00000000-0000-4000-8000-000000000123")).toBe("/learn/guides/00000000-0000-4000-8000-000000000123");
    for (const path of ["/projects/github/callback?code=private", "/projects/../account", "//github.com", "/learn/guides/../../account"]) expect(safeNext(path)).toBeNull();
  });
  it("does not fetch repositories or start authorization for a guest", () => {
    page();
    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/sign-in?next=%2Fprojects");
    expect(mocks.request).not.toHaveBeenCalled();
  });
  it("shows honest unavailable state without inventing connected repositories", async () => {
    mocks.auth = { status: "signed-in", userId: "owner-a" };
    mocks.request.mockRejectedValue(new Error("private provider error"));
    page();
    expect(await screen.findByRole("alert")).toHaveTextContent("Something went wrong");
    expect(screen.queryByText("private provider error")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Open fixture/ })).toBeNull();
  });
  it.each([
    [401, "Sign in again"],
    [404, "Not found"],
    [429, "going a little fast"],
    [504, "server took too long"],
  ] as const)("explains status %s safely without assuming missing App configuration or replaying the action", async (status, message) => {
    mocks.auth = { status: "signed-in", userId: "owner-a" };
    mocks.request.mockImplementation(async (path: string) => {
      if (path.endsWith("/installations/start")) throw new ApiError(status, "private-upstream-diagnostic-canary");
      return [];
    });
    const user = userEvent.setup();
    render(<ProjectsProviders><ConnectView /></ProjectsProviders>);
    await user.click(screen.getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: "Continue to GitHub" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(screen.getByRole("alert")).not.toHaveTextContent("App is not configured");
    expect(screen.queryByText("private-upstream-diagnostic-canary")).toBeNull();
    expect(mocks.request.mock.calls.filter(([path]) => path.endsWith("/installations/start"))).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Continue to GitHub" })).toBeEnabled();
  });
  it.each(["http://github.com/login/oauth/authorize", "https://github.com.evil.test/login/oauth/authorize", "https://github.com/repos/private", "https://user@github.com/login/oauth/authorize", "javascript:alert(1)"])("rejects an unsafe authorization address: %s", (url) => {
    expect(() => githubAuthorizationUrl(url, "authorize")).toThrow();
  });
  it("requires exact state and unexpired authorization before reading a callback", () => {
    saveGitHubAuthorization({ state: "opaque-state", expires_at: new Date(Date.now() + 60_000).toISOString(), installation_url: "https://github.com/apps/trace-example/installations/new", authorization_url: "https://github.com/login/oauth/authorize?client_id=public-example" });
    expect(pendingGitHubAuthorization("opaque-state").state).toBe("opaque-state");
    expect(() => pendingGitHubAuthorization("forged-state")).toThrow();
    saveGitHubAuthorization({ ...pendingGitHubAuthorization("opaque-state"), expires_at: new Date(0).toISOString() });
    expect(() => pendingGitHubAuthorization("opaque-state")).toThrow();
  });
});

const connectionId = "00000000-0000-4000-8000-000000000111";
const secondConnection = "00000000-0000-4000-8000-000000000222";
const commitSha = "a".repeat(40);
const knowledge: RepositoryKnowledge = {
  schema_version: "project-repository-v2", connection_id: connectionId, commit_sha: commitSha, digest: "b".repeat(64), complete_repository: false,
  repository: { repository_id: 22, full_name: "fixture/architecture", private: true, default_branch: "main" },
  catalog: [{ path: "backend/identity.py", kind: "file", blob_sha: "c".repeat(40), size: 48, category: "backend", content_included: true }],
  references: [{ reference_id: "d".repeat(64), digest: "e".repeat(64), path: "backend/identity.py", line_start: 1, line_end: 2, text: "def authenticate(subject):\n    return subject", kind: "source", category: "backend", blob_sha: "c".repeat(40), agent: null }], commits: [],
  coverage: { status: "partial", tree_complete: true, history_complete: true, changed_files_complete: true, catalog_entries: 1, fetched_files: 1, omitted_files: 2, reasons: ["excluded_path"], max_catalog_entries: 240, max_fetched_files: 18, max_file_bytes: 32768, max_references: 40, max_source_bytes: 48000, max_artifact_bytes: 98304, max_changed_files: 75, max_history_commits: 30, max_tree_requests: 20 },
};
const groundedAnswer: ProjectAnswer = {
  schema_version: "project-question-v1", status: "answered", commit_sha: commitSha, snapshot_digest: knowledge.digest, source: "test_fixture", selected_references: 1, limitations: ["Only bounded excerpts are available."], grading: "ungraded", execution_status: "not_executed", can_complete_lesson: false,
  sections: [{ explanation: "The helper returns the supplied subject; other authentication behavior is unknown.", citations: [{ reference_id: "d".repeat(64), path: "backend/identity.py", line_start: 2, line_end: 2, quote: "return subject" }] }],
};

function tutor(sha = commitSha, id = connectionId) { return <ProjectTutor connectionId={id} sha={sha} repository="fixture/architecture" />; }
async function openTutor(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: /Project tutor/ }));
}
async function ask(user: ReturnType<typeof userEvent.setup>, text: string) {
  await user.type(screen.getByLabelText("Ask about this project"), text);
  await user.click(screen.getByRole("button", { name: "Ask" }));
}

describe("Owned repository questions", () => {
  beforeEach(() => { mocks.auth = { status: "signed-in", userId: "owner-a" }; mocks.request.mockResolvedValue(groundedAnswer); });
  it("renders exact server citations and sends bounded dialogue instead of client evidence", async () => {
    const user = userEvent.setup(); render(tutor()); await openTutor(user);
    await ask(user, "Teach me authentication in this project.");
    expect(await screen.findByText(groundedAnswer.sections[0].explanation)).toBeVisible();
    expect(screen.getByText("backend/identity.py")).toBeVisible();
    expect(screen.getByText("Line 2")).toBeVisible();
    expect(screen.getByText("return subject")).toBeVisible();
    expect(screen.getByText(/Test fixture.*Ungraded.*Not executed/)).toBeVisible();
    expect(mocks.request.mock.calls[0][1]).toEqual({ commit_sha: commitSha, question: "Teach me authentication in this project.", history: [] });
    await ask(user, "Explain that return value.");
    await waitFor(() => expect(mocks.request).toHaveBeenCalledTimes(2));
    expect(mocks.request.mock.calls[1][1]).toEqual({ commit_sha: commitSha, question: "Explain that return value.", history: [{ role: "user", text: "Teach me authentication in this project." }, { role: "assistant", text: groundedAnswer.sections[0].explanation }] });
    expect(JSON.stringify(mocks.request.mock.calls[1][1])).not.toContain("owner-a");
  });
  it.each(["insufficient_information", "unavailable"] as const)("does not invent quotations for %s", async (status) => {
    mocks.request.mockResolvedValue({ ...groundedAnswer, status, source: "none", sections: [] });
    const user = userEvent.setup(); render(tutor()); await openTutor(user); await ask(user, "What does this code do?");
    await screen.findByText(status === "insufficient_information" ? /kept excerpts don't say enough/ : /couldn't return a validated answer/);
    expect(screen.queryByText("return subject")).toBeNull();
  });
  it.each(["owner", "commit", "repository"])("clears private conversation and drafts when the %s changes", async (context) => {
    const user = userEvent.setup(); const page = render(tutor()); await openTutor(user);
    await ask(user, "Explain this helper."); await screen.findByText(groundedAnswer.sections[0].explanation);
    await user.type(screen.getByLabelText("Ask about this project"), "private draft");
    if (context === "owner") mocks.auth = { status: "signed-in", userId: "owner-b" };
    page.rerender(tutor(context === "commit" ? "f".repeat(40) : commitSha, context === "repository" ? secondConnection : connectionId));
    expect(screen.queryByText(groundedAnswer.sections[0].explanation)).toBeNull();
    expect(screen.getByLabelText("Ask about this project")).toHaveValue("");
  });
  it("removes the tutor when a repository is disconnected", async () => {
    localStorage.setItem(`trace.project.sha.${connectionId}`, commitSha);
    let disconnected = false;
    mocks.request.mockImplementation(async (path: string) => {
      if (path.endsWith("/repositories")) return [{ id: connectionId, full_name: "fixture/architecture", status: disconnected ? "disconnected" : "connected" }];
      if (path.includes("/knowledge?")) return knowledge;
      if (path.endsWith("/ask")) return groundedAnswer;
      throw new ApiError(404, "not saved");
    });
    const { QueryClient, QueryClientProvider } = await import("@tanstack/react-query");
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const user = userEvent.setup(); render(<QueryClientProvider client={client}><ProjectView connectionId={connectionId} /></QueryClientProvider>);
    await screen.findByRole("button", { name: /Project tutor/ }); await openTutor(user);
    await ask(user, "Explain authentication"); await screen.findByText(groundedAnswer.sections[0].explanation);
    disconnected = true; await act(async () => { await client.invalidateQueries({ queryKey: ["projects", "owner-a", "connections"] }); });
    await screen.findByRole("heading", { name: "That project isn't available" });
    expect(screen.queryByText(groundedAnswer.sections[0].explanation)).toBeNull();
    expect(screen.queryByRole("dialog")).toBeNull(); localStorage.clear();
  });
});

describe("GitHub request admission", () => {
  it("serializes reads and user actions and skips aborted queued work", async () => {
    let release!: () => void;
    const held = new Promise<void>((done) => { release = done; });
    const calls: string[] = [];
    const first = githubQueue(async () => { calls.push("read"); await held; });
    const controller = new AbortController();
    const cancelled = githubQueue(async () => { calls.push("old owner"); }, controller.signal).catch((error: ApiError) => error.code);
    const action = githubQueue(async () => { calls.push("action"); });
    await Promise.resolve(); expect(calls).toEqual(["read"]);
    controller.abort(); release(); await first;
    expect(await cancelled).toBe("request_cancelled"); await action;
    expect(calls).toEqual(["read", "action"]);
  });
  it("keeps the lane usable through StrictMode replay", async () => {
    mocks.auth = { status: "signed-in", userId: "owner-a" };
    let active = 0, maximum = 0;
    mocks.request.mockImplementation(async () => { active++; maximum = Math.max(maximum, active); try { await Promise.resolve(); return []; } finally { active--; } });
    render(<StrictMode><GitHubProjects /></StrictMode>);
    await screen.findByRole("heading", { name: "Connect GitHub" });
    expect(maximum).toBe(1); expect(screen.queryByRole("alert")).toBeNull();
  });
  it("does not start queued old-account reads with the new credentials", async () => {
    mocks.auth = { status: "signed-in", userId: "owner-a" };
    let release!: () => void;
    const held = new Promise<void>((done) => { release = done; });
    const calls: { path: string; owner: string | undefined }[] = [];
    mocks.request.mockImplementation(async (path: string) => {
      const owner = mocks.auth.userId; calls.push({ path, owner });
      if (owner === "owner-a" && path.endsWith("/installations")) await held;
      return [];
    });
    const page = render(<GitHubProjects />);
    await waitFor(() => expect(calls).toHaveLength(1));
    mocks.auth = { status: "signed-in", userId: "owner-b" }; page.rerender(<GitHubProjects />);
    await act(async () => { release(); await held; });
    await screen.findByRole("heading", { name: "Connect GitHub" });
    expect(calls.filter((call) => call.owner === "owner-a" && call.path.endsWith("/repositories"))).toHaveLength(0);
    expect(calls.filter((call) => call.owner === "owner-b" && call.path.endsWith("/repositories"))).toHaveLength(1);
  });
  it("continues after a failed read without automatically replaying it", async () => {
    mocks.auth = { status: "signed-in", userId: "owner-a" };
    mocks.request.mockImplementation(async (path: string) => { if (path.endsWith("/repositories")) throw new ApiError(503, "private-source-error-canary"); return []; });
    page(); await screen.findByRole("alert");
    expect(mocks.request.mock.calls.filter(([path]) => path.endsWith("/installations"))).toHaveLength(1);
    expect(mocks.request.mock.calls.filter(([path]) => path.endsWith("/repositories"))).toHaveLength(1);
    expect(screen.queryByText("private-source-error-canary")).toBeNull();
  });
});


it("stops preparation before another write when the owner changes", async () => {
  mocks.auth = { status: "signed-in", userId: "owner-a" };
  localStorage.clear();
  let release!: () => void;
  const held = new Promise<void>((done) => { release = done; });
  mocks.request.mockImplementation(async (path: string) => {
    if (path.endsWith("/repositories")) return [{ id: connectionId, full_name: "fixture/architecture", status: "connected" }];
    if (path.endsWith("/sync")) { await held; return { commit_sha: commitSha, references: [], digest: "b".repeat(64) }; }
    throw new ApiError(404, "not saved");
  });
  const tree = () => <ProjectsProviders><ProjectView connectionId={connectionId} /></ProjectsProviders>;
  const user = userEvent.setup(); const page = render(tree());
  await user.type(await screen.findByLabelText("Commit ID"), commitSha);
  await user.click(screen.getByRole("button", { name: "Use this commit" }));
  await user.click(await screen.findByRole("button", { name: "Fetch snapshot and continue" }));
  await waitFor(() => expect(mocks.request.mock.calls.some(([path]) => path.endsWith("/sync"))).toBe(true));
  mocks.auth = { status: "signed-in", userId: "owner-b" }; page.rerender(tree());
  await act(async () => { release(); await held; });
  await screen.findByLabelText("Commit ID");
  expect(mocks.request.mock.calls.some(([path]) => path.endsWith("/ingest") || path.endsWith("/learning-path"))).toBe(false);
  localStorage.clear();
});
