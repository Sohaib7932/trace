import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GitHubProjects } from "@/components/projects/github-projects";
import { ApiError } from "@/lib/api/client";
import type { ProjectLearningPath, ProjectSnapshot } from "@/lib/api/github-projects";

const mocks = vi.hoisted(() => ({ auth: { status: "signed-in", userId: "owner-a" }, request: vi.fn() }));
vi.mock("@/lib/supabase/use-auth", () => ({ useAuth: () => mocks.auth }));
vi.mock("@/lib/api/client", async (original) => ({ ...await original<typeof import("@/lib/api/client")>(), protectedApiRequest: mocks.request }));

const connectionId = "00000000-0000-4000-8000-000000000111";
const otherConnection = "00000000-0000-4000-8000-000000000222";
const commitSha = "a".repeat(40);
const referenceId = "b".repeat(64);
const snapshot: ProjectSnapshot = {
  schema_version: "project-snapshot-v1", connection_id: connectionId, commit_sha: commitSha,
  digest: "c".repeat(64), references: [{ reference_id: referenceId, kind: "source", path: "alarm_clock.py", text: "def next_alarm(): return 'tomorrow'" }],
  omitted_files: 1, complete_repository: false,
};
const saved: ProjectLearningPath = {
  id: "00000000-0000-4000-8000-000000000333",
  generation: { provider_id: "mock", requested_model_id: "fixture-model", returned_model_id: "fixture-model", generated_at: "2026-11-05T01:00:00Z" },
  status: "ready", snapshot_digest: snapshot.digest, commit_sha: commitSha, source: "test_fixture",
  grading: "ungraded", execution_status: "not_executed", can_complete_lesson: false,
  content: { schema_version: "project-learning-v1", title: "Saved alarm learning path", steps: [{ title: "Inspect the next alarm", explanation: "The supplied function returns tomorrow.", question: "What does the supplied function return?", reference_ids: [referenceId] }] },
};

afterEach(cleanup);
beforeEach(() => { mocks.auth = { status: "signed-in", userId: "owner-a" }; mocks.request.mockReset(); });

function api(generate: () => Promise<ProjectLearningPath> = async () => saved, load: () => Promise<ProjectLearningPath> = async () => saved) {
  mocks.request.mockImplementation(async (path: string, body?: unknown) => {
    const id = mocks.auth.userId === "owner-b" ? otherConnection : connectionId;
    if (path.endsWith("/repositories")) return [{ id, repository_id: 22, installation_id: 11, full_name: "fixture/alarm", private: true, status: "connected" }];
    if (path.endsWith("/installations")) return [];
    if (path.endsWith("/sync")) return { ...snapshot, connection_id: id };
    if (path.endsWith("/learning-path")) { expect(body).toEqual({ commit_sha: commitSha }); return generate(); }
    if (path.endsWith(`/learning-path?commit_sha=${commitSha}`)) { expect(body).toBeUndefined(); return load(); }
    throw new Error("Unexpected fixture API path");
  });
}

async function pin(user: ReturnType<typeof userEvent.setup>, id = connectionId) {
  await screen.findByRole("option", { name: "fixture/alarm" });
  await user.selectOptions(screen.getByLabelText("Repository"), id);
  await user.type(screen.getByLabelText("Exact commit SHA"), commitSha);
  await user.click(screen.getByRole("button", { name: "Read this commit" }));
  await screen.findByRole("heading", { name: "Pinned snapshot" });
  await waitFor(() => expect(screen.getByRole("button", { name: "Generate grounded learning questions" })).toBeEnabled());
}

describe("Private persisted learning paths", () => {
  it("shows success only after the committed receipt response resolves", async () => {
    let resolve!: (value: ProjectLearningPath) => void;
    const pending = new Promise<ProjectLearningPath>((done) => { resolve = done; });
    api(() => pending);
    const user = userEvent.setup(); render(<GitHubProjects />); await pin(user);
    await user.click(screen.getByRole("button", { name: "Generate grounded learning questions" }));
    await waitFor(() => expect(mocks.request.mock.calls.some(([path]) => path.endsWith("/learning-path"))).toBe(true));
    expect(screen.queryByRole("heading", { name: saved.content!.title })).toBeNull();
    expect(screen.queryByText(/Saved privately/)).toBeNull();
    await act(async () => { resolve(saved); await pending; });
    expect(await screen.findByRole("heading", { name: saved.content!.title })).toBeVisible();
    expect(screen.getByText("Saved privately · Test fixture · Ungraded · Not executed")).toBeVisible();
    expect(screen.getAllByText("alarm_clock.py")).toHaveLength(2);
  });

  it("clears the earlier result when a new save fails without exposing the database error", async () => {
    let calls = 0;
    api(async () => {
      calls += 1;
      if (calls === 1) return saved;
      throw new ApiError(503, "private-database-failure-canary");
    });
    const user = userEvent.setup(); render(<GitHubProjects />); await pin(user);
    await user.click(screen.getByRole("button", { name: "Generate grounded learning questions" }));
    await screen.findByRole("heading", { name: saved.content!.title });
    await user.click(screen.getByRole("button", { name: "Generate grounded learning questions" }));
    await screen.findByRole("alert");
    expect(screen.queryByRole("heading", { name: saved.content!.title })).toBeNull();
    expect(screen.queryByText(/Saved privately/)).toBeNull();
    expect(screen.queryByText(/private-database-failure-canary/)).toBeNull();
    expect(calls).toBe(2);
  });

  it.each([
    { id: null },
    { generation: null },
    { source: "ai" as const },
    { status: "unavailable" as const, id: null, generation: null, content: null, source: "none" as const },
    { content: { ...saved.content!, steps: [{ ...saved.content!.steps[0], reference_ids: ["f".repeat(64)] }] } },
  ])("does not render success for an unconfirmed or inconsistent response %j", async (change) => {
    api(async () => ({ ...saved, ...change }));
    const user = userEvent.setup(); render(<GitHubProjects />); await pin(user);
    await user.click(screen.getByRole("button", { name: "Generate grounded learning questions" }));
    expect(await screen.findByText("A saved, validated learning path is unavailable. No result has been assumed.")).toBeVisible();
    expect(screen.queryByText(/Saved privately/)).toBeNull();
    expect(screen.queryByRole("heading", { name: saved.content!.title })).toBeNull();
  });

  it("loads the saved result after remount and pinning without another generation", async () => {
    const generate = vi.fn(async () => saved), load = vi.fn(async () => saved);
    api(generate, load);
    const user = userEvent.setup(); const view = render(<GitHubProjects />); await pin(user);
    await user.click(screen.getByRole("button", { name: "Generate grounded learning questions" }));
    await screen.findByRole("heading", { name: saved.content!.title });
    view.unmount(); render(<GitHubProjects />); await pin(user);
    expect(screen.queryByRole("heading", { name: saved.content!.title })).toBeNull();
    expect(load).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Load saved learning path" }));
    expect(await screen.findByRole("heading", { name: saved.content!.title })).toBeVisible();
    expect(generate).toHaveBeenCalledTimes(1);
    expect(load).toHaveBeenCalledTimes(1);
  });

  it("reports no saved path without automatically generating or retrying", async () => {
    const generate = vi.fn(async () => saved), load = vi.fn(async () => { throw new ApiError(404, "private-lookup-canary"); });
    api(generate, load);
    const user = userEvent.setup(); render(<GitHubProjects />); await pin(user);
    await user.click(screen.getByRole("button", { name: "Load saved learning path" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("No saved learning path is available for this repository and commit.");
    expect(screen.queryByText(/private-lookup-canary/)).toBeNull();
    expect(generate).not.toHaveBeenCalled(); expect(load).toHaveBeenCalledTimes(1);
  });

  it.each([{ commit_sha: "d".repeat(40) }, { snapshot_digest: "d".repeat(64) }])("does not display a receipt bound to a different pinned source %j", async (change) => {
    api(async () => ({ ...saved, ...change }));
    const user = userEvent.setup(); render(<GitHubProjects />); await pin(user);
    await user.click(screen.getByRole("button", { name: "Generate grounded learning questions" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Generate grounded learning questions" })).toBeEnabled());
    expect(screen.queryByRole("heading", { name: saved.content!.title })).toBeNull();
    expect(screen.queryByText(/Saved privately/)).toBeNull();
  });

  it("withholds a late result after the pinned commit changes", async () => {
    let resolve!: (value: ProjectLearningPath) => void;
    const pending = new Promise<ProjectLearningPath>((done) => { resolve = done; });
    api(() => pending);
    const user = userEvent.setup(); render(<GitHubProjects />); await pin(user);
    await user.click(screen.getByRole("button", { name: "Generate grounded learning questions" }));
    await waitFor(() => expect(mocks.request.mock.calls.some(([path]) => path.endsWith("/learning-path"))).toBe(true));
    await user.clear(screen.getByLabelText("Exact commit SHA"));
    await user.type(screen.getByLabelText("Exact commit SHA"), "d".repeat(40));
    await act(async () => { resolve(saved); await pending; });
    expect(screen.queryByRole("heading", { name: saved.content!.title })).toBeNull();
    expect(screen.queryByText(/Saved privately/)).toBeNull();
  });

  it("removes saved private content when the owner changes", async () => {
    api();
    const user = userEvent.setup(); const view = render(<GitHubProjects />); await pin(user);
    await user.click(screen.getByRole("button", { name: "Load saved learning path" }));
    await screen.findByRole("heading", { name: saved.content!.title });
    mocks.auth = { status: "signed-in", userId: "owner-b" };
    view.rerender(<GitHubProjects />);
    expect(screen.queryByRole("heading", { name: saved.content!.title })).toBeNull();
    expect(screen.queryByText(/Saved privately/)).toBeNull();
    await screen.findByRole("option", { name: "fixture/alarm" });
    expect(mocks.request.mock.calls.filter(([path]) => path.includes("learning-path"))).toHaveLength(1);
  });
});
