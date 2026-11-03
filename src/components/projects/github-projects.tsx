"use client";

import { useState } from "react";
import Link from "next/link";
import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/lib/supabase/use-auth";
import { ApiError } from "@/lib/api/client";
import { githubAuthorizationUrl, githubProjectsApi, saveGitHubAuthorization, type GitHubRepository, type ProjectLearningPath, type ProjectSnapshot } from "@/lib/api/github-projects";

export function GitHubProjects() {
  const [client] = useState(() => new QueryClient());
  return <QueryClientProvider client={client}><GitHubProjectContent /></QueryClientProvider>;
}

function GitHubProjectContent() {
  const auth = useAuth();
  const queries = useQueryClient();
  const owner = auth.status === "signed-in" ? auth.userId : undefined;
  const enabled = auth.status === "signed-in";
  const connections = useQuery({ queryKey: ["github-connections", owner], queryFn: githubProjectsApi.connections, enabled, retry: false });
  const installations = useQuery({ queryKey: ["github-installations", owner], queryFn: githubProjectsApi.installations, enabled, retry: false });
  const [choices, setChoices] = useState<{ owner: string | undefined; installation: number; repositories: GitHubRepository[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [connectionId, setConnectionId] = useState("");
  const [sha, setSha] = useState("");
  const [snapshot, setSnapshot] = useState<{ owner: string | undefined; value: ProjectSnapshot } | null>(null);
  const [path, setPath] = useState<{ owner: string | undefined; value: ProjectLearningPath } | null>(null);
  async function action(work: () => Promise<void>) {
    setBusy(true); setError("");
    try { await work(); } catch (failure) {
      setError(failure instanceof ApiError && failure.status === 409
        ? "Repository authorization needs renewing. Connect the GitHub App again."
        : "Project Learning is unavailable or its GitHub App is not configured. No repository connection or AI result is assumed. Try again after setup.");
    } finally { setBusy(false); }
  }
  if (auth.status === "loading") return <p role="status">Checking sign-in…</p>;
  if (!enabled) return <section><h1 className="type-h2">Learn from a project</h1><p className="mt-4">Sign in to connect selected repositories privately.</p><Link href="/sign-in?next=%2Fprojects" className="mt-4 inline-block underline">Sign in</Link></section>;
  const activeSnapshot = snapshot && snapshot.owner === owner && snapshot.value.connection_id === connectionId && snapshot.value.commit_sha === sha ? snapshot.value : null;
  const activePath = path && path.owner === owner && activeSnapshot && path.value.snapshot_digest === activeSnapshot.digest ? path.value : null;
  return <section className="max-w-3xl">
    <h1 className="type-h2">Project Learning</h1>
    <p className="mt-4 text-secondary">Connect a GitHub App with selected-repository, read-only access. This is separate from signing in with GitHub. External app configuration is required.</p>
    <p className="mt-2 text-secondary">Repository snapshots and grounded questions are private, bounded and ungraded. Trace does not run repository code or change your progress.</p>
    <button disabled={busy} className="mt-6 min-h-11 rounded-lg bg-foreground px-4 text-white disabled:opacity-50" onClick={() => void action(async () => {
      const start = await githubProjectsApi.start();
      const url = githubAuthorizationUrl(start.installation_url, "install");
      githubAuthorizationUrl(start.authorization_url, "authorize");
      saveGitHubAuthorization(start); window.location.assign(url);
    })}>Connect GitHub App</button>
    {(error || connections.error || installations.error) && <p role="alert" className="mt-4">{error || "GitHub App is not available. Ask the owner to configure it; no live repository access has been verified."}</p>}
    {installations.data?.map((installation) => <div key={installation.installation_id} className="mt-4">
      <button disabled={busy} className="min-h-11 underline" onClick={() => void action(async () => setChoices({ owner, installation: installation.installation_id, repositories: await githubProjectsApi.choices(installation.installation_id) }))}>Choose an allowed repository from installation {installation.installation_id}</button>
    </div>)}
    {choices && choices.owner === owner && choices.repositories.map((repo) => <div key={repo.repository_id} className="mt-2 flex flex-wrap items-center gap-4"><span>{repo.full_name} ({repo.private ? "private" : "public"})</span><button disabled={busy} className="min-h-11 underline" onClick={() => void action(async () => {
      const connected = await githubProjectsApi.connect(choices.installation, repo.repository_id); setConnectionId(connected.id);
      await queries.invalidateQueries({ queryKey: ["github-connections", owner] });
    })}>Use repository</button></div>)}
    <h2 className="type-h4 mt-10">Your connected repositories</h2>
    {connections.isLoading && <p role="status">Loading connections…</p>}
    {connections.data?.length === 0 && <p className="mt-3">No repositories connected.</p>}
    <label className="mt-4 block">Repository<select className="mt-2 block min-h-11 w-full rounded-lg border border-border p-2" value={connectionId} onChange={(event) => { setConnectionId(event.target.value); setSnapshot(null); setPath(null); }}><option value="">Select a repository</option>{connections.data?.map((repo) => <option value={repo.id} key={repo.id}>{repo.full_name}</option>)}</select></label>
    <label className="mt-4 block">Exact commit SHA<input value={sha} maxLength={40} onChange={(event) => { setSha(event.target.value.trim()); setSnapshot(null); setPath(null); }} placeholder="40 lowercase hexadecimal characters" className="mt-2 block min-h-11 w-full rounded-lg border border-border p-2 font-mono" /></label>
    <button disabled={busy || !connectionId || !/^[0-9a-f]{40}$/.test(sha)} className="mt-4 min-h-11 rounded-lg border px-4 disabled:opacity-50" onClick={() => void action(async () => { setSnapshot({ owner, value: await githubProjectsApi.sync(connectionId, sha) }); setPath(null); })}>Read this commit</button>
    {activeSnapshot && <section className="mt-6 rounded-xl border border-border p-4"><h2 className="type-h4">Pinned snapshot</h2><p className="mt-2 break-all font-mono text-sm">{activeSnapshot.commit_sha}</p><p className="mt-2">{activeSnapshot.references.length} references; {activeSnapshot.omitted_files} omitted files. This is not a complete repository analysis.</p>
      <p className="mt-3 text-secondary">Generating sends the filtered references below to Gemini. Do not connect a repository containing material you cannot share with the approved provider.</p>
      <details className="mt-3"><summary>Review source excerpts</summary><ul>{activeSnapshot.references.map((reference) => <li key={reference.reference_id} className="mt-3"><strong>{reference.path}</strong><pre className="mt-1 overflow-x-auto whitespace-pre-wrap break-words text-sm">{reference.text}</pre></li>)}</ul></details>
      <button disabled={busy} className="mt-4 min-h-11 rounded-lg bg-foreground px-4 text-white disabled:opacity-50" onClick={() => void action(async () => setPath({ owner, value: await githubProjectsApi.learningPath(connectionId, sha) }))}>Generate grounded learning questions</button>
    </section>}
    {busy && <p role="status" className="mt-4">Working… This may return unavailable.</p>}
    {activePath && <section className="mt-6">{activePath.status !== "ready" || !activePath.content ? <p role="status">Gemini could not produce a validated learning path. No result has been invented.</p> : <><h2 className="type-h3">{activePath.content.title}</h2><p className="mt-2">{activePath.source === "test_fixture" ? "Test fixture · " : "AI-generated · "}Ungraded · Not executed</p><ol>{activePath.content.steps.map((step, index) => <li key={index} className="mt-6"><h3 className="type-h4">{step.title}</h3><p className="mt-2 whitespace-pre-wrap">{step.explanation}</p><p className="mt-3 font-medium">{step.question}</p><ul className="mt-2 text-sm">{step.reference_ids.map((id) => <li key={id}>{activeSnapshot?.references.find((item) => item.reference_id === id)?.path ?? "Source unavailable"}</li>)}</ul></li>)}</ol></>}</section>}
  </section>;
}
