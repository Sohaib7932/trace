"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowRight, GitCommitHorizontal, Settings2 } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { CountUp } from "@/components/motion/count-up";
import { Enter } from "./enter";
import { githubProjectsApi } from "@/lib/api/github-projects";
import { isCommitSha, languagesOf, loadSha, reasonLabel, saveSha } from "@/lib/projects/format";
import { githubQueue } from "@/lib/projects/queue";
import { isValidatedPath } from "@/lib/projects/validated-path";
import { isNotFound, projectKeys, useConnections, useOwner, useSavedKnowledge, useSavedPath, useSavedSnapshot } from "@/lib/projects/use-projects";
import { Excerpt, LanguageChip, PipelineTracker, PrivateChip, RepoName, ShaChip, StatusChip, type Stage } from "./parts";
import { ProjectTutor } from "./project-tutor";
import { CardSkeleton, Crumbs, Notice, ProjectError } from "./shell";

type Step = "sync" | "ingest" | "path";
const EXCERPTS_AT_FIRST = 6;

export function ProjectView({ connectionId }: { connectionId: string }) {
  const owner = useOwner();
  return <ScopedProjectView key={`${owner}:${connectionId}`} connectionId={connectionId} />;
}

function ScopedProjectView({ connectionId }: { connectionId: string }) {
  const owner = useOwner();
  const queries = useQueryClient();
  const connections = useConnections();
  const project = connections.data?.find((item) => item.id === connectionId && item.status !== "disconnected");
  const [sha, setSha] = useState(() => loadSha(connectionId));
  const [draft, setDraft] = useState(() => loadSha(connectionId));
  const [busy, setBusy] = useState<Step | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [failedStep, setFailedStep] = useState<Step | null>(null);
  const [showAll, setShowAll] = useState(false);
  const snapshot = useSavedSnapshot(connectionId, sha);
  const knowledge = useSavedKnowledge(connectionId, sha);
  const path = useSavedPath(connectionId, sha);
  const action = useRef<AbortController | null>(null);
  useEffect(() => () => { action.current?.abort(); }, []);

  if (!connections.data) return connections.error ? <ProjectError error={connections.error} onRetry={() => void connections.refetch()} /> : <CardSkeleton count={2} />;
  if (connections.error) return <ProjectError error={connections.error} onRetry={() => void connections.refetch()} />;
  if (!project) {
    return (
      <Notice title="That project isn't available" detail="It may have been disconnected, or it belongs to another account.">
        <Link href="/projects" className="mt-5 inline-flex min-h-11 items-center rounded-[11px] bg-foreground px-5 font-medium text-white hover:bg-foreground/85">Back to projects</Link>
      </Notice>
    );
  }

  const pinned = isCommitSha(sha);
  const snapshotValue = snapshot.data;
  const knowledgeValue = knowledge.data;
  const pathValue = path.data;
  const pathReady = isValidatedPath(pathValue, snapshotValue, sha);
  const unexpected = (query: { error: unknown }) => (query.error && !isNotFound(query.error) ? query.error : null);
  const readError = unexpected(snapshot) ?? unexpected(knowledge) ?? unexpected(path);

  function pin() {
    const value = draft.trim().toLowerCase();
    if (!isCommitSha(value)) return;
    action.current?.abort();
    setBusy(null);
    saveSha(connectionId, value);
    setSha(value); setError(null); setFailedStep(null); setShowAll(false);
  }

  async function run(step: Step, signal?: AbortSignal): Promise<boolean> {
    if (!signal) {
      action.current?.abort();
      action.current = new AbortController();
      signal = action.current.signal;
    }
    if (signal.aborted) return false;
    setError(null); setFailedStep(null); setBusy(step);
    try {
      if (step === "sync") queries.setQueryData(projectKeys.snapshot(owner, connectionId, sha), await githubQueue(() => githubProjectsApi.sync(connectionId, sha), signal));
      if (step === "ingest") queries.setQueryData(projectKeys.knowledge(owner, connectionId, sha), await githubQueue(() => githubProjectsApi.ingest(connectionId, sha), signal));
      if (step === "path") queries.setQueryData(projectKeys.path(owner, connectionId, sha), await githubQueue(() => githubProjectsApi.learningPath(connectionId, sha), signal));
      return !signal.aborted;
    } catch (failure) {
      if (!signal.aborted) { setError(failure); setFailedStep(step); }
      return false;
    } finally { if (!signal.aborted) setBusy(null); }
  }
  async function prepare() {
    action.current?.abort();
    action.current = new AbortController();
    const signal = action.current.signal;
    for (const step of ["sync", "ingest", "path"] as const) if (!(await run(step, signal))) return;
  }

  const stage = (done: boolean, step: Step, active: string, idle: string, ok: string): Pick<Stage, "state" | "detail"> =>
    busy === step ? { state: "active", detail: active } : failedStep === step ? { state: "failed", detail: "That step didn't finish." } : done ? { state: "done", detail: ok } : { state: "todo", detail: idle };
  const stages: Stage[] = [
    { id: "connected", label: "Connected", state: "done", detail: "Read-only access to this repository." },
    { id: "pinned", label: "Commit pinned", state: pinned ? "done" : "todo", detail: pinned ? "Everything is tied to this exact commit." : "Choose the commit to learn from." },
    { id: "fetch", label: "Fetching", ...stage(Boolean(snapshotValue), "sync", "Fetching a snapshot…", "Waiting for a pinned commit.", "Snapshot saved.") },
    { id: "index", label: "Indexing", ...stage(Boolean(knowledgeValue), "ingest", "Reading files and history…", "Not read yet.", "Repository read.") },
    { id: "analyze", label: "Analyzing", ...stage(pathReady, "path", "Writing questions from your code…", "No learning path yet.", "Questions are ready.") },
    { id: "ready", label: "Path ready", state: pathReady ? "done" : pathValue?.status === "unavailable" ? "failed" : "todo", detail: pathReady ? "Open the learning path." : pathValue?.status === "unavailable" ? "A validated path couldn't be produced for this commit." : "Not generated yet." },
  ];

  const languages = languagesOf(knowledgeValue);
  const references = knowledgeValue?.references ?? [];
  const nextStep: Step | null = !pinned ? null : !snapshotValue ? "sync" : !knowledgeValue ? "ingest" : !pathReady ? "path" : null;
  const label = nextStep === "sync" ? "Fetch snapshot" : nextStep === "ingest" ? "Read the repository" : "Generate learning path";

  return (
    <div className="grid gap-8 pb-24">
      <Crumbs items={[{ label: "Projects", href: "/projects" }, { label: project.full_name }]} />
      <Enter>
        <section aria-label="Project" className="pj-card flex flex-wrap items-center justify-between gap-4 p-5 sm:p-6">
          <div className="min-w-0 flex-1">
            <h2 className="text-[1.25rem] font-semibold tracking-[-0.02em]"><RepoName fullName={project.full_name} /></h2>
            <div className="mt-2 flex flex-wrap items-center gap-2"><PrivateChip isPrivate={project.private} /><StatusChip tone="ok">Connected</StatusChip>{pinned && <ShaChip sha={sha} />}{languages.map((item) => <LanguageChip key={item.name} name={item.name} files={item.files} />)}</div>
          </div>
          <Link href={`/projects/${encodeURIComponent(connectionId)}/manage`} className="inline-flex min-h-11 items-center gap-2 rounded-[11px] border border-border-strong px-4 text-[0.9375rem] font-medium hover:bg-surface-muted"><Settings2 aria-hidden="true" className="size-4" strokeWidth={1.8} />Manage</Link>
        </section>
      </Enter>

      <Enter delay={80}>
        <section aria-labelledby="pin-title" className="pj-card p-5 sm:p-6">
          <div className="flex items-center gap-3"><span aria-hidden="true" className="pj-icon"><GitCommitHorizontal className="size-4" strokeWidth={1.8} /></span><h2 id="pin-title" className="text-[1.0625rem] font-semibold">Choose the commit to learn from</h2></div>
          <p className="mt-2 max-w-[62ch] text-[0.9375rem] leading-relaxed text-secondary">Paste the full 40-character commit ID from GitHub (Commits, then copy the full SHA). Every excerpt and answer stays tied to this exact commit, so it never drifts when the code changes.</p>
          <form className="mt-4 flex flex-wrap items-start gap-3" onSubmit={(event) => { event.preventDefault(); pin(); }}>
            <label className="min-w-0 flex-1 basis-72 text-[0.875rem] font-medium">Commit ID
              <input value={draft} onChange={(event) => setDraft(event.target.value.trim().toLowerCase())} maxLength={40} spellCheck={false} autoComplete="off" autoCapitalize="off" aria-invalid={draft.length > 0 && !isCommitSha(draft)} aria-describedby="sha-help" placeholder="40 lowercase letters and numbers" className="pj-input pj-mono mt-1.5" />
            </label>
            <button type="submit" disabled={!isCommitSha(draft) || draft === sha} className="mt-[1.625rem] inline-flex min-h-11 items-center rounded-[11px] bg-foreground px-5 font-medium text-white hover:bg-foreground/85 disabled:cursor-not-allowed disabled:opacity-45">Use this commit</button>
          </form>
          <p id="sha-help" role="status" className="mt-2 text-[0.8125rem] text-secondary">{draft.length === 0 ? "Trace can't look up your latest commit for you yet." : isCommitSha(draft) ? (draft === sha ? "This commit is in use." : "Looks right.") : `${draft.length} of 40 characters. Use lowercase letters a–f and numbers only.`}</p>
        </section>
      </Enter>

      <Enter delay={140}>
        <section aria-labelledby="progress-title" className="pj-card p-5 sm:p-6">
          <h2 id="progress-title" className="text-[1.0625rem] font-semibold">Progress</h2>
          <div className="mt-5"><PipelineTracker stages={stages} /></div>
          <div className="mt-6 flex flex-wrap items-center gap-3">
            {pinned && (nextStep || busy) && (
              <button type="button" disabled={busy !== null} onClick={() => void prepare()} className="inline-flex min-h-11 items-center gap-2 rounded-[11px] bg-[linear-gradient(180deg,#ff934f,#ff7a2e)] px-5 font-semibold text-foreground shadow-[inset_0_1px_0_rgba(255,255,255,0.45),0_6px_16px_-6px_rgba(232,116,59,0.7)] disabled:cursor-not-allowed disabled:opacity-60">
                {busy ? "Working…" : `${label}${nextStep !== "path" ? " and continue" : ""}`}
              </button>
            )}
            {pathReady && <Link href={`/projects/${encodeURIComponent(connectionId)}/path?sha=${sha}`} className="inline-flex min-h-11 items-center gap-2 rounded-[11px] bg-foreground px-5 font-medium text-white hover:bg-foreground/85">Open the learning path<ArrowRight aria-hidden="true" className="size-4" strokeWidth={1.8} /></Link>}
            {!pinned && <p className="text-[0.9375rem] text-secondary">Pick a commit above to begin.</p>}
          </div>
          {pinned && nextStep && <p className="mt-3 max-w-[64ch] text-[0.8125rem] leading-relaxed text-secondary">Generating a path sends short, filtered excerpts of this commit to the AI provider. Don&apos;t connect a repository with material you can&apos;t share with it. Repository code is never run.</p>}
          <div aria-live="polite">{busy && <p role="status" className="mt-3 text-[0.875rem] text-secondary">{busy === "sync" ? "Fetching the snapshot from GitHub…" : busy === "ingest" ? "Reading files and history. Larger projects take longer." : "Writing questions from your code…"}</p>}</div>
          {error ? <ProjectError className="mt-4" error={error} onRetry={failedStep ? () => void run(failedStep) : undefined} /> : null}
          {readError ? <ProjectError className="mt-4" error={readError} onRetry={() => { void snapshot.refetch(); void knowledge.refetch(); void path.refetch(); }} /> : null}
        </section>
      </Enter>

      {knowledgeValue && (
        <Enter>
          <section aria-labelledby="read-title" className="pj-card p-5 sm:p-6">
            <h2 id="read-title" className="text-[1.0625rem] font-semibold">What Trace read</h2>
            <dl className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-5">
              {[["Files listed", knowledgeValue.catalog.length], ["Files read", knowledgeValue.coverage.fetched_files], ["Files skipped", knowledgeValue.coverage.omitted_files], ["Excerpts kept", references.length], ["Commits seen", knowledgeValue.commits?.length ?? 0]].map(([name, value]) => (
                <div key={name as string} className="pj-stat"><dd className="text-[1.5rem] font-semibold tracking-[-0.03em] tabular-nums"><CountUp value={value as number} /></dd><dt className="text-[0.8125rem] text-secondary">{name}</dt></div>
              ))}
            </dl>
            <p className="mt-4 text-[0.875rem] leading-relaxed text-secondary">
              {knowledgeValue.coverage.tree_complete && knowledgeValue.coverage.omitted_files === 0 ? "Everything in the file list was read." : "This is a partial read, so questions only cover what was kept."}
              {(knowledgeValue.coverage.reasons?.length ?? 0) > 0 && <> Skipped or limited: {knowledgeValue.coverage.reasons!.map(reasonLabel).join("; ")}.</>}
            </p>
            <h3 className="mt-6 text-[0.9375rem] font-semibold">Excerpts that can be used</h3>
            <div className="mt-3 grid grid-cols-[minmax(0,1fr)] gap-3">
              {references.slice(0, showAll ? undefined : EXCERPTS_AT_FIRST).map((reference) => (
                <Excerpt key={reference.reference_id} path={reference.path} text={reference.text} sha={knowledgeValue.commit_sha} lineStart={reference.line_start} lineEnd={reference.line_end}
                  note={reference.agent ? `AI-agent log · ${reference.agent.model ?? "model unknown"} · the link between prompt and file is unproven` : undefined} />
              ))}
            </div>
            {references.length > EXCERPTS_AT_FIRST && <button type="button" onClick={() => setShowAll(!showAll)} className="mt-3 min-h-11 font-medium underline underline-offset-4">{showAll ? "Show fewer" : `Show all ${references.length}`}</button>}
          </section>
        </Enter>
      )}

      {knowledgeValue && <ProjectTutor connectionId={connectionId} sha={sha} repository={project.full_name} />}
    </div>
  );
}
