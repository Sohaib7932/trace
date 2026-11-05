import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PathView } from "@/components/projects/path-view";
import { ProjectsProviders } from "@/components/projects/shell";
import { ApiError } from "@/lib/api/client";
import type { ProjectLearningPath, ProjectSnapshot } from "@/lib/api/github-projects";

const mocks = vi.hoisted(() => ({ auth: { status: "signed-in", userId: "owner-a" }, request: vi.fn() }));
vi.mock("@/lib/supabase/use-auth", () => ({ useAuth: () => mocks.auth }));
vi.mock("@/lib/api/client", async (original) => ({ ...await original<typeof import("@/lib/api/client")>(), protectedApiRequest: mocks.request }));

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

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
beforeEach(() => { mocks.auth = { status: "signed-in", userId: "owner-a" }; mocks.request.mockReset(); localStorage.clear(); });

function view(sha = commitSha) { return <ProjectsProviders><PathView connectionId={connectionId} sha={sha} /></ProjectsProviders>; }
function api(generate: () => Promise<ProjectLearningPath> = async () => saved, load: () => Promise<ProjectLearningPath> = async () => { throw new ApiError(404, "not saved"); }) {
  mocks.request.mockImplementation(async (path: string, body?: unknown) => {
    if (path.endsWith("/repositories")) return [{ id: mocks.auth.userId === "owner-b" ? otherConnection : connectionId, full_name: "fixture/alarm", status: "connected" }];
    if (path.includes("/snapshot?")) return snapshot;
    if (path.includes("/knowledge?")) throw new ApiError(404, "not read");
    if (path.endsWith("/learning-path")) { expect(body).toEqual({ commit_sha: commitSha }); return generate(); }
    if (path.includes("/learning-path?")) { expect(body).toBeUndefined(); return load(); }
    throw new Error("Unexpected fixture API path");
  });
}

describe("Private persisted learning paths", () => {
  it("shows success only after the committed receipt response resolves", async () => {
    let resolve!: (value: ProjectLearningPath) => void;
    const pending = new Promise<ProjectLearningPath>((done) => { resolve = done; });
    api(() => pending);
    const user = userEvent.setup(); render(view());
    await user.click(await screen.findByRole("button", { name: "Generate learning path" }));
    await waitFor(() => expect(mocks.request.mock.calls.some(([path]) => path.endsWith("/learning-path"))).toBe(true));
    try { expect(screen.queryByRole("heading", { name: saved.content!.title })).toBeNull(); }
    finally { await act(async () => { resolve(saved); await pending; }); }
    expect(await screen.findByRole("heading", { name: saved.content!.title })).toBeVisible();
    expect(screen.getByText("Test fixture")).toBeVisible();
    expect(screen.getByText("Not executed")).toBeVisible();
    expect(screen.getByText(/Practice only.*ungraded/)).toBeVisible();
  });

  it("clears an earlier result when regeneration fails without exposing the database error", async () => {
    const generate = vi.fn(async () => { throw new ApiError(503, "private-database-failure-canary"); });
    api(generate, async () => saved);
    const user = userEvent.setup(); render(view());
    await user.click(await screen.findByRole("button", { name: "Generate again" }));
    await screen.findByRole("alert");
    expect(screen.queryByRole("heading", { name: saved.content!.title })).toBeNull();
    expect(screen.queryByText(/private-database-failure-canary/)).toBeNull();
    expect(generate).toHaveBeenCalledTimes(1);
  });

  it.each([
    { id: null }, { generation: null }, { source: "ai" as const },
    { status: "unavailable" as const, id: null, generation: null, content: null, source: "none" as const },
    { content: { ...saved.content!, steps: [{ ...saved.content!.steps[0], reference_ids: ["f".repeat(64)] }] } },
    { commit_sha: "d".repeat(40) }, { snapshot_digest: "d".repeat(64) },
  ])("withholds an inconsistent generated receipt %j", async (change) => {
    api(async () => ({ ...saved, ...change }));
    const user = userEvent.setup(); render(view());
    await user.click(await screen.findByRole("button", { name: "Generate learning path" }));
    expect(await screen.findByRole("heading", { name: "No validated path for this commit" })).toBeVisible();
    expect(screen.queryByRole("heading", { name: saved.content!.title })).toBeNull();
  });

  it("loads a saved receipt after remount without generating again", async () => {
    const generate = vi.fn(async () => saved), load = vi.fn(async () => saved);
    api(generate, load);
    const first = render(view());
    await screen.findByRole("heading", { name: saved.content!.title });
    first.unmount(); render(view());
    await screen.findByRole("heading", { name: saved.content!.title });
    expect(generate).not.toHaveBeenCalled(); expect(load).toHaveBeenCalledTimes(2);
  });

  it("reports no saved path without automatically generating or retrying", async () => {
    const generate = vi.fn(async () => saved), load = vi.fn(async () => { throw new ApiError(404, "private-lookup-canary"); });
    api(generate, load); render(view());
    await screen.findByRole("heading", { name: "No learning path yet" });
    expect(screen.queryByText(/private-lookup-canary/)).toBeNull();
    expect(generate).not.toHaveBeenCalled(); expect(load).toHaveBeenCalledTimes(1);
  });

  it("withholds a late result after the pinned commit changes", async () => {
    let resolve!: (value: ProjectLearningPath) => void;
    const pending = new Promise<ProjectLearningPath>((done) => { resolve = done; });
    api(() => pending);
    const user = userEvent.setup(); const page = render(view());
    await user.click(await screen.findByRole("button", { name: "Generate learning path" }));
    await waitFor(() => expect(mocks.request.mock.calls.some(([path]) => path.endsWith("/learning-path"))).toBe(true));
    page.rerender(view("d".repeat(40)));
    await act(async () => { resolve(saved); await pending; });
    await screen.findByRole("heading", { name: "No learning path yet" });
    expect(screen.queryByRole("heading", { name: saved.content!.title })).toBeNull();
  });

  it("removes saved private content when the owner changes", async () => {
    api(async () => saved, async () => saved);
    const page = render(view());
    await screen.findByRole("heading", { name: saved.content!.title });
    mocks.auth = { status: "signed-in", userId: "owner-b" }; page.rerender(view());
    expect(screen.queryByRole("heading", { name: saved.content!.title })).toBeNull();
    await screen.findByRole("heading", { name: "That project isn't available" });
  });
});
