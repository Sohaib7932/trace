import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { GitHubProjects } from "@/components/projects/github-projects";
import { clearGitHubAuthorization, githubAuthorizationUrl, pendingGitHubAuthorization, saveGitHubAuthorization } from "@/lib/api/github-projects";
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
