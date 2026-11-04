"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/lib/supabase/use-auth";
import { ApiError } from "@/lib/api/client";
import { githubAuthorizationUrl, githubProjectsApi, saveGitHubAuthorization, type GitHubRepository, type ProjectLearningPath, type ProjectSnapshot, type RepositoryKnowledge, type ProjectAnswer } from "@/lib/api/github-projects";

export function GitHubProjects() {
  const [client] = useState(() => new QueryClient());
  const auth = useAuth();
  const identity = auth.status === "signed-in" ? auth.userId : auth.status;
  return <QueryClientProvider client={client}><GitHubProjectContent key={identity} /></QueryClientProvider>;
}

function GitHubProjectContent() {
  const auth = useAuth();
  const queries = useQueryClient();
  const owner = auth.status === "signed-in" ? auth.userId : undefined;
  const enabled = auth.status === "signed-in";
  const requestTail = useRef<Promise<void>>(Promise.resolve());
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
  // The server admits one active GitHub request per account. Queue each request,
  // not the whole action: actions can await query invalidation and its refetch.
  const runRequest = useCallback(<T,>(work: () => Promise<T>, signal?: AbortSignal): Promise<T> => {
    const stopped = () => !mounted.current || signal?.aborted;
    const response = requestTail.current.then(async () => {
      if (stopped()) throw new ApiError(0, "Request stopped.", "request_cancelled");
      const result = await work();
      if (stopped()) throw new ApiError(0, "Request stopped.", "request_cancelled");
      return result;
    });
    requestTail.current = response.then(() => undefined, () => undefined);
    return response;
  }, []);
  const connections = useQuery({ queryKey: ["github-connections", owner], queryFn: ({ signal }) => runRequest(githubProjectsApi.connections, signal), enabled, retry: false });
  const installations = useQuery({ queryKey: ["github-installations", owner], queryFn: ({ signal }) => runRequest(githubProjectsApi.installations, signal), enabled, retry: false });
  const [choices, setChoices] = useState<{ owner: string | undefined; installation: number; repositories: GitHubRepository[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [connectionId, setConnectionId] = useState("");
  const [sha, setSha] = useState("");
  const [snapshot, setSnapshot] = useState<{ owner: string | undefined; value: ProjectSnapshot } | null>(null);
  const [path, setPath] = useState<{ owner: string | undefined; value: ProjectLearningPath } | null>(null);
  const [knowledge, setKnowledge] = useState<{ owner: string | undefined; value: RepositoryKnowledge } | null>(null);
  const [question, setQuestion] = useState("");
  const [answers, setAnswers] = useState<{ owner: string | undefined; connection: string; sha: string; turns: { question: string; answer: ProjectAnswer }[] } | null>(null);
  function clearContent() { setSnapshot(null); setPath(null); setKnowledge(null); setAnswers(null); setQuestion(""); }
  async function action(work: () => Promise<void>) {
    setBusy(true); setError("");
    try { await work(); } catch (failure) {
      const statusMessages: Partial<Record<number, string>> = {
        401: "Your sign-in needs renewing. Sign in again before continuing with Project Learning.",
        404: "This repository is unavailable or does not belong to your account. Select an available connection.",
        409: "Repository authorization needs renewing. Connect the GitHub App again.",
        429: "Project Learning request limit reached. Wait before trying again.",
        504: "Project Learning took too long. The result is unconfirmed; check the current state before trying again.",
      };
      setError((failure instanceof ApiError ? statusMessages[failure.status] : undefined)
        ?? "Project Learning is unavailable or its GitHub App is not configured. No repository connection or AI result is assumed. Try again after setup.");
    } finally { setBusy(false); }
  }
  if (auth.status === "loading") return <p role="status">Checking sign-in…</p>;
  if (!enabled) return <section><h1 className="type-h2">Learn from a project</h1><p className="mt-4">Sign in to connect selected repositories privately.</p><Link href="/sign-in?next=%2Fprojects" className="mt-4 inline-block underline">Sign in</Link></section>;
  const activeSnapshot = snapshot && snapshot.owner === owner && snapshot.value.connection_id === connectionId && snapshot.value.commit_sha === sha ? snapshot.value : null;
  const activePath = path && path.owner === owner && activeSnapshot && path.value.snapshot_digest === activeSnapshot.digest ? path.value : null;
  const activeKnowledge = knowledge && knowledge.owner === owner && knowledge.value.connection_id === connectionId && knowledge.value.commit_sha === sha ? knowledge.value : null;
  const activeAnswers = answers && answers.owner === owner && answers.connection === connectionId && answers.sha === sha ? answers.turns : [];
  const connected = connections.data?.find((item) => item.id === connectionId && item.status !== "disconnected");
  return <section className="max-w-3xl">
    <h1 className="type-h2">Project Learning</h1>
    <p className="mt-4 text-secondary">Connect a GitHub App with selected-repository, read-only access. This is separate from signing in with GitHub. External app configuration is required.</p>
    <p className="mt-2 text-secondary">Repository snapshots and grounded questions are private, bounded and ungraded. Trace does not run repository code or change your progress.</p>
    <button disabled={busy} className="mt-6 min-h-11 rounded-lg bg-foreground px-4 text-white disabled:opacity-50" onClick={() => void action(async () => {
      const start = await runRequest(githubProjectsApi.start);
      const url = githubAuthorizationUrl(start.installation_url, "install");
      githubAuthorizationUrl(start.authorization_url, "authorize");
      saveGitHubAuthorization(start); window.location.assign(url);
    })}>Connect GitHub App</button>
    {(error || connections.error || installations.error) && <p role="alert" className="mt-4">{error || "GitHub App is not available. Ask the owner to configure it; no live repository access has been verified."}</p>}
    {installations.data?.map((installation) => <div key={installation.installation_id} className="mt-4">
      <p className="text-sm">Installation {installation.installation_id}: {installation.status === "disconnected" ? "disconnected" : installation.status === "reauthorization_required" ? "reconnect required" : "authorized"}</p>
      <button disabled={busy || installation.status === "disconnected" || installation.status === "reauthorization_required"} className="min-h-11 underline disabled:opacity-50" onClick={() => void action(async () => setChoices({ owner, installation: installation.installation_id, repositories: await runRequest(() => githubProjectsApi.choices(installation.installation_id)) }))}>Choose an allowed repository from installation {installation.installation_id}</button>
      <button disabled={busy || installation.status === "disconnected"} className="ml-4 min-h-11 underline disabled:opacity-50" onClick={() => void action(async () => {
        await runRequest(() => githubProjectsApi.disconnectInstallation(installation.installation_id)); clearContent(); setChoices(null); setConnectionId("");
        await queries.invalidateQueries({ queryKey: ["github-installations", owner] });
        await queries.invalidateQueries({ queryKey: ["github-connections", owner] });
      })}>Disconnect installation from Trace</button>
    </div>)}
    {choices && choices.owner === owner && choices.repositories.map((repo) => <div key={repo.repository_id} className="mt-2 flex flex-wrap items-center gap-4"><span>{repo.full_name} ({repo.private ? "private" : "public"})</span><button disabled={busy} className="min-h-11 underline" onClick={() => void action(async () => {
      const connected = await runRequest(() => githubProjectsApi.connect(choices.installation, repo.repository_id)); setConnectionId(connected.id); clearContent();
      await queries.invalidateQueries({ queryKey: ["github-connections", owner] });
    })}>Use repository</button></div>)}
    <h2 className="type-h4 mt-10">Your connected repositories</h2>
    {connections.isLoading && <p role="status">Loading connections…</p>}
    {connections.data?.length === 0 && <p className="mt-3">No repositories connected.</p>}
    <label className="mt-4 block">Repository<select className="mt-2 block min-h-11 w-full rounded-lg border border-border p-2" value={connectionId} onChange={(event) => { setConnectionId(event.target.value); clearContent(); }}><option value="">Select a repository</option>{connections.data?.filter((repo) => repo.status !== "disconnected").map((repo) => <option value={repo.id} key={repo.id}>{repo.full_name}</option>)}</select></label>
    {connected && <button disabled={busy} className="mt-2 min-h-11 underline" onClick={() => void action(async () => {
      await runRequest(() => githubProjectsApi.disconnect(connectionId)); clearContent(); setConnectionId("");
      await queries.invalidateQueries({ queryKey: ["github-connections", owner] });
    })}>Disconnect this repository from Trace</button>}
    <label className="mt-4 block">Exact commit SHA<input value={sha} maxLength={40} onChange={(event) => { setSha(event.target.value.trim()); clearContent(); }} placeholder="40 lowercase hexadecimal characters" className="mt-2 block min-h-11 w-full rounded-lg border border-border p-2 font-mono" /></label>
    <p className="mt-2 text-sm text-secondary">Copy the full commit SHA from GitHub. Source references stay pinned to that exact revision. Disconnect stops Trace access and preserves private history; it does not uninstall the GitHub App.</p>
    <button disabled={busy || !connectionId || !/^[0-9a-f]{40}$/.test(sha)} className="mt-4 min-h-11 rounded-lg border px-4 disabled:opacity-50" onClick={() => void action(async () => { setSnapshot({ owner, value: await runRequest(() => githubProjectsApi.sync(connectionId, sha)) }); setPath(null); })}>Read this commit</button>
    <button disabled={busy || !connected || !/^[0-9a-f]{40}$/.test(sha)} className="mt-4 ml-3 min-h-11 rounded-lg bg-foreground px-4 text-white disabled:opacity-50" onClick={() => void action(async () => {
      clearContent(); setKnowledge({ owner, value: await runRequest(() => githubProjectsApi.ingest(connectionId, sha)) });
    })}>Read repository for questions</button>
    {activeKnowledge && <section className="mt-6 rounded-xl border border-border p-4">
      <h2 className="type-h4">Repository knowledge</h2>
      <p className="mt-2">{activeKnowledge.catalog.length} catalog entries · {activeKnowledge.coverage.fetched_files} files read · {activeKnowledge.references.length} source excerpts · {activeKnowledge.commits?.length ?? 0} commits</p>
      <p className="mt-2 text-sm text-secondary">Bounded, partial coverage. {activeKnowledge.coverage.omitted_files} files omitted. {activeKnowledge.coverage.reasons?.join(", ") || "Full repository understanding is not assumed."}</p>
      <details className="mt-3"><summary>Review pinned source material before sending it to Gemini</summary>
        <ul>{activeKnowledge.references.map((reference) => <li key={reference.reference_id} className="mt-3"><strong>{reference.path}:{reference.line_start}–{reference.line_end}</strong>
          {reference.agent && <p className="text-sm">Agent log · {reference.agent.model ?? "model unknown"} · {reference.agent.timestamp ?? "timestamp unknown"} · prompt-to-file relationship unproven</p>}
          <pre className="mt-1 overflow-x-auto whitespace-pre-wrap break-words text-sm">{reference.text}</pre></li>)}</ul>
      </details>
      <form className="mt-5" onSubmit={(event) => { event.preventDefault(); if (!question.trim() || busy) return; void action(async () => {
        const submitted = question.trim();
        const history = activeAnswers.filter((turn) => turn.answer.status === "answered").slice(-2).flatMap((turn) => [
          { role: "user" as const, text: turn.question.slice(0, 1600) },
          { role: "assistant" as const, text: turn.answer.sections.map((section) => section.explanation).join("\n").slice(0, 1600) },
        ]);
        const answer = await runRequest(() => githubProjectsApi.ask(connectionId, { commit_sha: sha, question: submitted, history }));
        setAnswers({ owner, connection: connectionId, sha, turns: [...activeAnswers, { question: submitted, answer }].slice(-6) }); setQuestion("");
      }); }}>
        <label className="block">Ask about this project<textarea value={question} maxLength={2000} onChange={(event) => setQuestion(event.target.value)} placeholder="Teach me how authentication works in this project." className="mt-2 min-h-24 w-full rounded-lg border border-border p-3" /></label>
        <p className="mt-2 text-sm text-secondary">Only retrieved excerpts are sent to Gemini. Answers are ungraded explanations with exact source citations; repository code is never executed.</p>
        <button disabled={busy || !question.trim()} className="mt-3 min-h-11 rounded-lg bg-foreground px-4 text-white disabled:opacity-50">Ask grounded question</button>
      </form>
      <div aria-live="polite">{activeAnswers.map((turn, index) => <article key={index} className="mt-6 border-t border-border pt-4"><h3 className="font-medium">{turn.question}</h3>
        {turn.answer.status !== "answered" ? <p className="mt-2">{turn.answer.status === "insufficient_information" ? "The ingested sources do not provide enough information for this question." : "Gemini could not return a validated grounded answer. No answer was invented."}</p> : <>
          <p className="mt-2 text-sm text-secondary">{turn.answer.source === "test_fixture" ? "Test fixture" : "AI-generated"} · Ungraded · Not executed</p>
          {turn.answer.sections.map((section, sectionIndex) => <div key={sectionIndex} className="mt-3"><p className="whitespace-pre-wrap">{section.explanation}</p><ul className="mt-2 text-sm">{section.citations.map((citation, citationIndex) => <li key={citationIndex} className="mt-2"><strong>{citation.path}:{citation.line_start}–{citation.line_end}</strong><blockquote className="mt-1 whitespace-pre-wrap break-words border-l-2 border-border pl-3">{citation.quote}</blockquote></li>)}</ul></div>)}
        </>}
      </article>)}</div>
    </section>}
    {activeSnapshot && <section className="mt-6 rounded-xl border border-border p-4"><h2 className="type-h4">Pinned snapshot</h2><p className="mt-2 break-all font-mono text-sm">{activeSnapshot.commit_sha}</p><p className="mt-2">{activeSnapshot.references.length} references; {activeSnapshot.omitted_files} omitted files. This is not a complete repository analysis.</p>
      <p className="mt-3 text-secondary">Generating sends the filtered references below to Gemini. Do not connect a repository containing material you cannot share with the approved provider.</p>
      <details className="mt-3"><summary>Review source excerpts</summary><ul>{activeSnapshot.references.map((reference) => <li key={reference.reference_id} className="mt-3"><strong>{reference.path}</strong><pre className="mt-1 overflow-x-auto whitespace-pre-wrap break-words text-sm">{reference.text}</pre></li>)}</ul></details>
      <button disabled={busy} className="mt-4 min-h-11 rounded-lg bg-foreground px-4 text-white disabled:opacity-50" onClick={() => void action(async () => setPath({ owner, value: await runRequest(() => githubProjectsApi.learningPath(connectionId, sha)) }))}>Generate grounded learning questions</button>
    </section>}
    {busy && <p role="status" className="mt-4">Working… This may return unavailable.</p>}
    {activePath && <section className="mt-6">{activePath.status !== "ready" || !activePath.content ? <p role="status">Gemini could not produce a validated learning path. No result has been invented.</p> : <><h2 className="type-h3">{activePath.content.title}</h2><p className="mt-2">{activePath.source === "test_fixture" ? "Test fixture · " : "AI-generated · "}Ungraded · Not executed</p><ol>{activePath.content.steps.map((step, index) => <li key={index} className="mt-6"><h3 className="type-h4">{step.title}</h3><p className="mt-2 whitespace-pre-wrap">{step.explanation}</p><p className="mt-3 font-medium">{step.question}</p><ul className="mt-2 text-sm">{step.reference_ids.map((id) => <li key={id}>{activeSnapshot?.references.find((item) => item.reference_id === id)?.path ?? "Source unavailable"}</li>)}</ul></li>)}</ol></>}</section>}
  </section>;
}
