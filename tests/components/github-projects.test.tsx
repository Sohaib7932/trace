import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { GitHubProjects } from "@/components/projects/github-projects";
import { ApiError } from "@/lib/api/client";
import { clearGitHubAuthorization, githubAuthorizationUrl, pendingGitHubAuthorization, saveGitHubAuthorization, type ProjectAnswer, type RepositoryKnowledge } from "@/lib/api/github-projects";
import { safeNext } from "@/lib/auth/next-path";
import config from "../../next.config";

const mocks = vi.hoisted(() => ({ auth: { status: "guest" } as { status: string; userId?: string }, request: vi.fn() }));
vi.mock("@/lib/supabase/use-auth", () => ({ useAuth: () => mocks.auth }));
vi.mock("@/lib/api/client", async (original) => ({ ...await original<typeof import("@/lib/api/client")>(), protectedApiRequest: mocks.request }));
afterEach(() => { cleanup(); clearGitHubAuthorization(); });
beforeEach(() => { mocks.auth = { status: "guest" }; mocks.request.mockReset(); });
function page() { return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><GitHubProjects /></QueryClientProvider>); }

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
    expect(await screen.findByRole("alert")).toHaveTextContent("GitHub App is not available");
    expect(screen.queryByText("private provider error")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Read this commit" })).toBeDisabled();
  });
  it.each([
    [401, "Your sign-in needs renewing. Sign in again before continuing with Project Learning."],
    [404, "This repository is unavailable or does not belong to your account. Select an available connection."],
    [429, "Project Learning request limit reached. Wait before trying again."],
    [504, "Project Learning took too long. The result is unconfirmed; check the current state before trying again."],
  ] as const)("explains status %s safely without assuming missing App configuration or replaying the action", async (status, message) => {
    mocks.auth = { status: "signed-in", userId: "owner-a" };
    mocks.request.mockImplementation(async (path: string) => {
      if (path.endsWith("/installations/start")) throw new ApiError(status, "private-upstream-diagnostic-canary");
      return [];
    });
    const user = userEvent.setup();
    page();
    await screen.findByText("No repositories connected.");
    await user.click(screen.getByRole("button", { name: "Connect GitHub App" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(screen.getByRole("alert")).not.toHaveTextContent("App is not configured");
    expect(screen.queryByText("private-upstream-diagnostic-canary")).toBeNull();
    expect(mocks.request.mock.calls.filter(([path]) => path.endsWith("/installations/start"))).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Connect GitHub App" })).toBeEnabled();
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

function projectApi(answer: ProjectAnswer = groundedAnswer) {
  let disconnected = false;
  mocks.auth = { status: "signed-in", userId: "owner-a" };
  mocks.request.mockImplementation(async (path: string) => {
    const id = mocks.auth.userId === "owner-b" ? secondConnection : connectionId;
    if (path.endsWith("/installations")) return [];
    if (path.endsWith("/repositories")) return [{ id, repository_id: 22, installation_id: 11, full_name: "fixture/architecture", private: true, status: disconnected ? "disconnected" : "connected" }];
    if (path.endsWith("/ingest")) return { ...knowledge, connection_id: id };
    if (path.endsWith("/ask")) return answer;
    if (path.endsWith("/disconnect")) { disconnected = true; return { id, status: "disconnected" }; }
    throw new Error("Unexpected test API path");
  });
}

async function readKnowledge(user: ReturnType<typeof userEvent.setup>, id = connectionId) {
  await screen.findByRole("option", { name: "fixture/architecture" });
  await user.selectOptions(screen.getByLabelText("Repository"), id);
  await user.clear(screen.getByLabelText("Exact commit SHA"));
  await user.type(screen.getByLabelText("Exact commit SHA"), commitSha);
  await user.click(screen.getByRole("button", { name: "Read repository for questions" }));
  await screen.findByRole("heading", { name: "Repository knowledge" });
}

describe("Owned repository questions", () => {
  it("renders exact server citations and sends bounded dialogue instead of client evidence", async () => {
    projectApi();
    const user = userEvent.setup();
    page(); await readKnowledge(user);
    await user.type(screen.getByLabelText("Ask about this project"), "Teach me authentication in this project.");
    await user.click(screen.getByRole("button", { name: "Ask grounded question" }));
    expect(await screen.findByText(groundedAnswer.sections[0].explanation)).toBeVisible();
    expect(screen.getByText("backend/identity.py:2–2")).toBeVisible();
    expect(screen.getByText("return subject")).toBeVisible();
    expect(screen.getByText("Test fixture · Ungraded · Not executed")).toBeVisible();
    const first = mocks.request.mock.calls.find(([path]) => path.endsWith("/ask"));
    expect(first?.[1]).toEqual({ commit_sha: commitSha, question: "Teach me authentication in this project.", history: [] });
    await user.type(screen.getByLabelText("Ask about this project"), "Explain that return value.");
    await user.click(screen.getByRole("button", { name: "Ask grounded question" }));
    await waitFor(() => expect(mocks.request.mock.calls.filter(([path]) => path.endsWith("/ask"))).toHaveLength(2));
    const second = mocks.request.mock.calls.filter(([path]) => path.endsWith("/ask"))[1];
    expect(second[1]).toEqual({ commit_sha: commitSha, question: "Explain that return value.", history: [{ role: "user", text: "Teach me authentication in this project." }, { role: "assistant", text: groundedAnswer.sections[0].explanation }] });
    expect(JSON.stringify(second[1])).not.toContain("owner-a");
  });

  it.each(["insufficient_information", "unavailable"] as const)("does not invent quotations for %s responses", async (status) => {
    projectApi({ ...groundedAnswer, status, source: "none", sections: [] });
    const user = userEvent.setup(); page(); await readKnowledge(user);
    await user.type(screen.getByLabelText("Ask about this project"), "An unsupported or unavailable question");
    await user.click(screen.getByRole("button", { name: "Ask grounded question" }));
    expect(await screen.findByText(status === "insufficient_information" ? "The ingested sources do not provide enough information for this question." : "Gemini could not return a validated grounded answer. No answer was invented.")).toBeVisible();
    expect(screen.queryByText("backend/identity.py:2–2")).toBeNull();
    expect(screen.queryByText("Test fixture · Ungraded · Not executed")).toBeNull();
  });

  it("clears private answers, knowledge and draft questions when repository context or owner changes", async () => {
    projectApi();
    const user = userEvent.setup(); const view = page(); await readKnowledge(user);
    await user.type(screen.getByLabelText("Ask about this project"), "Draft for the previous account");
    await user.clear(screen.getByLabelText("Exact commit SHA"));
    expect(screen.queryByRole("heading", { name: "Repository knowledge" })).toBeNull();
    await user.type(screen.getByLabelText("Exact commit SHA"), commitSha);
    await user.click(screen.getByRole("button", { name: "Read repository for questions" }));
    expect(await screen.findByLabelText("Ask about this project")).toHaveValue("");
    await user.type(screen.getByLabelText("Ask about this project"), "Another private owner draft");
    mocks.auth = { status: "signed-in", userId: "owner-b" };
    view.rerender(<GitHubProjects />);
    expect(screen.queryByRole("heading", { name: "Repository knowledge" })).toBeNull();
    await readKnowledge(user, secondConnection);
    expect(screen.getByLabelText("Ask about this project")).toHaveValue("");
    expect(screen.queryByText(groundedAnswer.sections[0].explanation)).toBeNull();
  });

  it("disconnect immediately removes source material and further question controls", async () => {
    projectApi();
    const user = userEvent.setup(); page(); await readKnowledge(user);
    await user.type(screen.getByLabelText("Ask about this project"), "Explain authentication");
    await user.click(screen.getByRole("button", { name: "Ask grounded question" }));
    await screen.findByText(groundedAnswer.sections[0].explanation);
    await user.click(screen.getByRole("button", { name: "Disconnect this repository from Trace" }));
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Repository knowledge" })).toBeNull());
    expect(screen.queryByText(groundedAnswer.sections[0].explanation)).toBeNull();
    expect(screen.queryByRole("button", { name: "Ask grounded question" })).toBeNull();
    expect(screen.getByRole("button", { name: "Read repository for questions" })).toBeDisabled();
  });
});
