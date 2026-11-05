"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { Enter } from "./enter";
import { githubProjectsApi } from "@/lib/api/github-projects";
import { isCommitSha, loadSha } from "@/lib/projects/format";
import { githubQueue } from "@/lib/projects/queue";
import { isValidatedPath } from "@/lib/projects/validated-path";
import { isNotFound, projectKeys, useConnections, useOwner, useSavedKnowledge, useSavedPath, useSavedSnapshot } from "@/lib/projects/use-projects";
import { RepoName, ShaChip, StatusChip } from "./parts";
import { PathPlayer } from "./path-player";
import { ProjectTutor } from "./project-tutor";
import { CardSkeleton, Crumbs, Notice, ProjectError } from "./shell";

/** The learning path for one repository at one commit. Questions and sources come from the server; nothing is graded here. */
export function PathView({ connectionId, sha: given }: { connectionId: string; sha?: string }) {
  const owner = useOwner();
  return <ScopedPathView key={`${owner}:${connectionId}:${given ?? ""}`} connectionId={connectionId} sha={given} />;
}

function ScopedPathView({ connectionId, sha: given }: { connectionId: string; sha?: string }) {
  const owner = useOwner();
  const queries = useQueryClient();
  const connections = useConnections();
  const project = connections.data?.find((item) => item.id === connectionId && item.status !== "disconnected");
  const sha = given && isCommitSha(given) ? given : loadSha(connectionId);
  const snapshot = useSavedSnapshot(connectionId, sha);
  const knowledge = useSavedKnowledge(connectionId, sha);
  const path = useSavedPath(connectionId, sha);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  if (connections.isPending) return <CardSkeleton count={2} />;
  if (connections.error) return <ProjectError error={connections.error} onRetry={() => void connections.refetch()} />;
  const back = `/projects/${encodeURIComponent(connectionId)}`;
  if (!project) return <Notice title="That project isn't available" detail="It may have been disconnected, or it belongs to another account."><Link href="/projects" className="mt-5 inline-flex min-h-11 items-center rounded-[11px] bg-foreground px-5 font-medium text-white hover:bg-foreground/85">Back to projects</Link></Notice>;
  if (!isCommitSha(sha)) return <Notice title="Choose a commit first" detail="A learning path belongs to one exact commit of your repository."><Link href={back} className="mt-5 inline-flex min-h-11 items-center rounded-[11px] bg-foreground px-5 font-medium text-white hover:bg-foreground/85">Go to the project</Link></Notice>;

  const loading = path.isPending || snapshot.isPending;
  const unexpected = [path.error, snapshot.error].find((failure) => failure && !isNotFound(failure));
  const value = path.data;
  const sources = new Map<string, { path: string; text: string; lineStart?: number; lineEnd?: number }>();
  for (const reference of snapshot.data?.references ?? []) sources.set(reference.reference_id, { path: reference.path, text: reference.text });
  // Knowledge references carry line ranges; prefer them when the same excerpt is there.
  for (const reference of knowledge.data?.references ?? []) sources.set(reference.reference_id, { path: reference.path, text: reference.text, lineStart: reference.line_start, lineEnd: reference.line_end });

  // The path is only shown when it matches this commit's snapshot and every source it cites is present.
  const valid = value && !error && isValidatedPath(value, snapshot.data, sha);

  async function generate() {
    setBusy(true); setError(null);
    try { queries.setQueryData(projectKeys.path(owner, connectionId, sha), await githubQueue(() => githubProjectsApi.learningPath(connectionId, sha))); }
    catch (failure) { setError(failure); }
    finally { setBusy(false); }
  }

  const steps = valid ? value.content!.steps : [];
  return (
    <div className="grid gap-8 pb-24">
      <Crumbs items={[{ label: "Projects", href: "/projects" }, { label: project.full_name, href: back }, { label: "Learning path" }]} />
      <div className="flex flex-wrap items-center gap-2"><RepoName fullName={project.full_name} className="max-w-[22rem] text-[0.9375rem] font-medium" /><ShaChip sha={sha} /><StatusChip tone="off">Practice only · ungraded</StatusChip></div>

      {loading ? <CardSkeleton count={2} /> : unexpected ? <ProjectError error={unexpected} onRetry={() => { void path.refetch(); void snapshot.refetch(); }} /> : !snapshot.data ? (
        <Notice title="Fetch the snapshot first" detail="A path can only be checked against a saved snapshot of this commit.">
          <Link href={back} className="mt-5 inline-flex min-h-11 items-center rounded-[11px] bg-foreground px-5 font-medium text-white hover:bg-foreground/85">Go to the project</Link>
        </Notice>
      ) : !valid ? (
        <Enter>
          <section aria-labelledby="none-title" className="pj-card p-6 sm:p-8">
            <h2 id="none-title" className="type-h3">{value ? "No validated path for this commit" : "No learning path yet"}</h2>
            <p className="mt-2 max-w-[60ch] text-secondary">{value?.status === "unavailable" ? "The AI couldn't produce a path that passes Trace's checks for this commit, so nothing is shown. You can try again." : value ? "The saved path doesn't match this commit's snapshot, so it isn't shown." : "Generate questions written from the excerpts of this commit."}</p>
            <p className="mt-3 max-w-[60ch] text-[0.8125rem] leading-relaxed text-secondary">Generating sends short, filtered excerpts of this commit to the AI provider. Repository code is never run.</p>
            <button type="button" disabled={busy} onClick={() => void generate()} className="mt-5 inline-flex min-h-11 items-center rounded-[11px] bg-[linear-gradient(180deg,#ff934f,#ff7a2e)] px-5 font-semibold text-foreground shadow-[inset_0_1px_0_rgba(255,255,255,0.45),0_6px_16px_-6px_rgba(232,116,59,0.7)] disabled:opacity-60">{busy ? "Writing questions…" : "Generate learning path"}</button>
            {error ? <ProjectError className="mt-4" error={error} onRetry={() => void generate()} /> : null}
          </section>
        </Enter>
      ) : (
        <>
          <Enter>
            <section aria-label="Path" className="pj-card p-6 sm:p-8">
              <p className="pj-eyebrow">Learning path</p>
              <h2 className="type-h3 mt-2">{value.content!.title}</h2>
              <div className="mt-3 flex flex-wrap items-center gap-2 text-[0.8125rem]">
                <span className="pj-chip">{value.source === "test_fixture" ? "Test fixture" : "AI-generated"}</span>
                {value.generation && <span className="pj-chip">{new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value.generation.generated_at))}</span>}
                <span className="pj-chip">Not executed</span>
              </div>
              <p className="mt-4 max-w-[62ch] text-[0.875rem] leading-relaxed text-secondary">These questions are practice. Trace doesn&apos;t grade them, and finishing a project path doesn&apos;t count toward lessons or the leaderboard. Ask the project tutor if you want to talk one through.</p>
            </section>
          </Enter>

          <PathPlayer owner={owner} connectionId={connectionId} sha={sha} pathId={value.id!} title={value.content!.title} steps={steps} repository={project.full_name} canExplain={Boolean(knowledge.data)} filesByStep={steps.map((item) => [...new Set(item.reference_ids.map((id) => sources.get(id)?.path).filter((value): value is string => Boolean(value)))])} repoPaths={[...new Set((knowledge.data?.references ?? snapshot.data?.references ?? []).map((item) => item.path))]} />

          <div className="flex flex-wrap items-center gap-3">
            <button type="button" disabled={busy} onClick={() => void generate()} className="inline-flex min-h-11 items-center rounded-[11px] border border-border-strong px-5 font-medium hover:bg-surface-muted disabled:opacity-60">{busy ? "Writing questions…" : "Generate again"}</button>
            <Link href={`${back}/manage`} className="min-h-11 content-center font-medium underline underline-offset-4">Manage this project</Link>
          </div>
          {error ? <ProjectError error={error} onRetry={() => void generate()} /> : null}
          {knowledge.data && <ProjectTutor connectionId={connectionId} sha={sha} repository={project.full_name} suggestions={steps.slice(0, 3).map((step) => `Help me think through: ${step.question}`.slice(0, 600))} />}
          {!knowledge.data && <p className="text-[0.8125rem] text-secondary">The project tutor needs the repository to be read first. Open the project and choose &ldquo;Read the repository&rdquo;.</p>}
        </>
      )}
    </div>
  );
}
