import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StrictMode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GitHubProjectCallback } from "@/components/projects/github-callback";
import { ConnectView } from "@/components/projects/connect";
import { ProjectsProviders } from "@/components/projects/shell";
import { ApiError } from "@/lib/api/client";
import { githubAuthorizationDiagnostic, type GitHubAuthorizationPresence, type GitHubAuthorizationStage } from "@/lib/api/github-authorization-diagnostics";
import { clearGitHubAuthorization, pendingGitHubAuthorization, saveGitHubAuthorization, type GitHubStart } from "@/lib/api/github-projects";

const mocks = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("@/lib/supabase/use-auth", () => ({ useAuth: () => ({ status: "signed-in", userId: "synthetic-owner" }) }));
vi.mock("@/lib/api/client", async (original) => ({ ...await original<typeof import("@/lib/api/client")>(), protectedApiRequest: mocks.request }));

const location = { search: "", assign: vi.fn(), replace: vi.fn() };
const replaceState = vi.fn();
let start: GitHubStart;
beforeEach(() => {
  mocks.request.mockReset(); location.assign.mockReset(); location.replace.mockReset(); replaceState.mockReset(); location.search = "";
  // Simulate browser navigation only; no GitHub authorization or token exchange
  // is claimed by these component tests. Preserve the real DOM for rendering.
  vi.stubGlobal("window", new Proxy(window, { get: (target, key) => key === "location" ? location : key === "history" ? { replaceState } : Reflect.get(target, key, target) }));
  start = { state: "synthetic-state", expires_at: new Date(Date.now() + 60_000).toISOString(), installation_url: "https://github.com/apps/trace-fixture/installations/new?state=synthetic-state", authorization_url: "https://github.com/login/oauth/authorize?client_id=fixture&state=synthetic-state" };
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); clearGitHubAuthorization(); vi.unstubAllGlobals(); });

function diagnostic() { return JSON.parse(screen.getByTestId("github-authorization-diagnostic").textContent ?? "{}"); }

describe("GitHub authorization entry points", () => {
  it.each([
    ["Continue to GitHub", "installation_url", false],
    ["Already installed? Sign in with GitHub", "authorization_url", false],
  ] as const)("%s starts a fresh flow using the correct backend URL", async (button, destination, installed) => {
    mocks.request.mockImplementation(async (path: string) => path.endsWith("/installations/start") ? start : installed ? [{ id: "i", status: "connected" }] : []);
    const user = userEvent.setup(); render(<ProjectsProviders><ConnectView /></ProjectsProviders>);
    await user.click(screen.getByRole("checkbox"));
    await user.click(await screen.findByRole("button", { name: button }));
    await waitFor(() => expect(location.assign).toHaveBeenCalledWith(start[destination]));
    expect(pendingGitHubAuthorization(start.state)).toEqual(start);
    expect(mocks.request.mock.calls.filter(([path]) => path.endsWith("/installations/start"))).toHaveLength(1);
    expect(mocks.request.mock.calls.some(([path]) => path.endsWith("/installations/complete"))).toBe(false);
  });
});

describe("GitHub authorization callback", () => {
  it.each([undefined, 11])("completes once with optional installation %s and strips the sensitive query first", async (installation) => {
    saveGitHubAuthorization({ ...start, ...(installation ? { installation_id: installation } : {}) });
    // A URL-supplied installation ID must not override the saved setup selection
    // or become an unverified selection in the authorization-only flow.
    location.search = "?code=synthetic-code&state=synthetic-state&installation_id=999";
    mocks.request.mockImplementation(async (_path, body) => {
      expect(replaceState).toHaveBeenCalledWith(null, "", "/projects/github/callback");
      expect(body).toEqual({ state: start.state, code: "synthetic-code", ...(installation ? { installation_id: installation } : {}) });
      return { installation_id: 11, repository_selection: "selected" };
    });
    render(<StrictMode><GitHubProjectCallback /></StrictMode>);
    await waitFor(() => expect(location.replace).toHaveBeenCalledWith("/projects/import"), { timeout: 3000 });
    expect(mocks.request).toHaveBeenCalledTimes(1);
    expect(mocks.request.mock.calls[0][0]).toBe("/projects/github/installations/complete");
    expect(location.assign).not.toHaveBeenCalled();
    expect(() => pendingGitHubAuthorization(start.state)).toThrow();
    expect(screen.queryByTestId("github-authorization-diagnostic")).toBeNull();
  });

  it("retains the first-time installation callback, then starts user authorization", async () => {
    saveGitHubAuthorization(start);
    location.search = "?installation_id=11&state=synthetic-state&setup_action=install";
    render(<GitHubProjectCallback />);
    await waitFor(() => expect(location.assign).toHaveBeenCalledWith(start.authorization_url));
    expect(pendingGitHubAuthorization(start.state).installation_id).toBe(11);
    expect(mocks.request).not.toHaveBeenCalled();
    expect(replaceState).toHaveBeenCalledWith(null, "", "/projects/github/callback");
  });

  it.each(["mismatch", "expired", "missing", "denied", "invalid-installation"])("rejects %s locally without exchanging a code", async (kind) => {
    if (kind !== "missing") saveGitHubAuthorization({ ...start, ...(kind === "expired" ? { expires_at: new Date(0).toISOString() } : {}) });
    location.search = kind === "invalid-installation" ? "?installation_id=-1&state=synthetic-state"
      : `?code=synthetic-code&state=${kind === "mismatch" ? "wrong-state" : start.state}${kind === "denied" ? "&error=access_denied" : ""}`;
    render(<GitHubProjectCallback />);
    await waitFor(() => expect(screen.queryAllByText(kind === "denied" ? /You stopped before finishing/ : /expired|needs|Start again|Start a fresh|didn.t send back/).length).toBeGreaterThan(0));
    expect(mocks.request).not.toHaveBeenCalled();
    expect(location.assign).not.toHaveBeenCalled(); expect(location.replace).not.toHaveBeenCalled();
    expect(replaceState).toHaveBeenCalledWith(null, "", "/projects/github/callback");
    expect(document.body.textContent).not.toContain("synthetic-code");
    if (kind === "denied") return;
    expect(() => pendingGitHubAuthorization(start.state)).toThrow(); // a stopped authorization is a user choice: no failure diagnostic is shown
    const stages: Record<string, string> = { mismatch: "state_mismatch", expired: "expired", missing: "pending_missing", denied: "provider_declined", "invalid-installation": "installation_id_invalid" };
    expect(diagnostic().failure_stage).toBe(stages[kind]);
    expect(diagnostic().callback_code_present).toBe(kind !== "invalid-installation");
    expect(diagnostic().callback_state_present).toBe(true);
    expect(diagnostic().provider_error_present).toBe(kind === "denied");
    if (kind === "missing") expect(diagnostic().pending_present).toBe(false);
    if (kind === "denied") expect(diagnostic()).not.toHaveProperty("pending_present");
    expect(screen.getByTestId("github-authorization-diagnostic").textContent).not.toMatch(/synthetic-state|synthetic-code|wrong-state|https?:/);
  });

  it.each([
    [401, "Sign in again"], [403, "That didn't work"],
    [404, "Not found"], [409, "That changed on the server"],
    [429, "going a little fast"], [504, "took too long"], [503, "server had a problem"],
  ] as const)("shows a safe status %s failure and never retries the one-use callback", async (status, message) => {
    saveGitHubAuthorization(start); location.search = "?code=synthetic-code&state=synthetic-state";
    mocks.request.mockRejectedValue(new ApiError(status, "private-upstream-secret-canary"));
    render(<GitHubProjectCallback />);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(message));
    expect(mocks.request).toHaveBeenCalledTimes(1);
    expect(location.replace).not.toHaveBeenCalled(); expect(location.assign).not.toHaveBeenCalled();
    expect(() => pendingGitHubAuthorization(start.state)).toThrow();
    expect(screen.getByRole("alert")).not.toHaveTextContent("private-upstream-secret-canary");
    expect(diagnostic().failure_stage).toBe("completion_call");
    expect(diagnostic().pending_present).toBe(true);
    expect(diagnostic().saved_state_present).toBe(true);
    expect(screen.getByTestId("github-authorization-diagnostic").textContent).not.toContain("private-upstream-secret-canary");
  });
});

describe("Value-free authorization diagnostics", () => {
  it.each([
    ["malformed", "pending_json_invalid"],
    ["invalid-expiry", "expiry_invalid"],
    ["invalid-url", "authorization_url_invalid"],
  ] as const)("identifies %s without exposing stored values", async (kind, stage) => {
    saveGitHubAuthorization({ ...start, ...(kind === "invalid-expiry" ? { expires_at: "private-expiry-canary" } : {}), ...(kind === "invalid-url" ? { authorization_url: "https://evil.test/private-url-canary" } : {}) });
    if (kind === "malformed") sessionStorage.setItem("trace-github-app-authorization-v1", "{private-json-canary");
    location.search = "?code=private-code-canary&state=synthetic-state";
    render(<GitHubProjectCallback />);
    await screen.findByTestId("github-authorization-diagnostic");
    expect(diagnostic().failure_stage).toBe(stage);
    expect(diagnostic().pending_present).toBe(true);
    expect(mocks.request).not.toHaveBeenCalled();
    expect(screen.getByTestId("github-authorization-diagnostic").textContent).not.toMatch(/canary|synthetic-state|https?:/);
  });

  it("reports blocked storage as unobserved, even if cleanup also throws", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("private-storage-canary"); });
    vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => { throw new Error("private-cleanup-canary"); });
    location.search = "?code=synthetic-code&state=synthetic-state";
    render(<GitHubProjectCallback />);
    await screen.findByTestId("github-authorization-diagnostic");
    expect(diagnostic()).toEqual({ version: 1, failure_stage: "pending_read_failed", callback_state_present: true, callback_code_present: true, callback_installation_present: false, provider_error_present: false });
    expect(mocks.request).not.toHaveBeenCalled();
    expect(location.assign).not.toHaveBeenCalled(); expect(location.replace).not.toHaveBeenCalled();
  });

  it.each(["start_request", "start_url_validation", "start_storage", "start_navigation"] as const)("records %s failures before clearing the safe UI error", async (stage) => {
    mocks.request.mockImplementation(async (path: string) => {
      if (!path.endsWith("/installations/start")) return [];
      if (stage === "start_request") throw new Error("private-request-canary");
      return stage === "start_url_validation" ? { ...start, authorization_url: "https://evil.test/private-url-canary" } : start;
    });
    if (stage === "start_storage") vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("private-storage-canary"); });
    if (stage === "start_navigation") location.assign.mockImplementationOnce(() => { throw new Error("private-navigation-canary"); });
    const user = userEvent.setup(); render(<ProjectsProviders><ConnectView /></ProjectsProviders>);
    await user.click(screen.getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: "Continue to GitHub" }));
    await screen.findByTestId("github-authorization-diagnostic");
    expect(diagnostic().failure_stage).toBe(stage);
    if (stage === "start_request") expect(diagnostic()).not.toHaveProperty("start_state_present");
    else expect(diagnostic().start_state_present).toBe(true);
    expect(screen.getByTestId("github-authorization-diagnostic").textContent).not.toMatch(/canary|synthetic-state|https?:/);
    expect(mocks.request.mock.calls.filter(([path]) => path.endsWith("/installations/start"))).toHaveLength(1);
  });

  it("copies only known boolean fields and allowlisted stages", () => {
    const untrusted = { pending_present: true, callback_code_present: "private-code-canary", state: "private-state-canary", token: "private-token-canary", url: "https://evil.test/private" } as unknown as GitHubAuthorizationPresence;
    expect(githubAuthorizationDiagnostic("private-stage-canary" as GitHubAuthorizationStage, untrusted)).toEqual({ version: 1, failure_stage: "unexpected", pending_present: true });
  });

  it("never emits callback parameters or raw errors to the DOM or console", async () => {
    const consoleSpies = (["log", "info", "warn", "error", "debug"] as const).map(method => vi.spyOn(console, method));
    saveGitHubAuthorization({ ...start, state: "private-state-canary" });
    location.search = "?code=private-code-canary&state=private-state-canary&error=private-error-canary&error_description=private-token-canary";
    render(<GitHubProjectCallback />);
    await screen.findByText(/You stopped before finishing/);
    expect(document.body.textContent).not.toContain("canary");
    for (const spy of consoleSpies) expect(spy).not.toHaveBeenCalled();
    expect(mocks.request).not.toHaveBeenCalled();
  });
});
