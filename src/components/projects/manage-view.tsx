"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { CountUp } from "@/components/motion/count-up";
import { Enter } from "./enter";
import { githubProjectsApi } from "@/lib/api/github-projects";
import { isCommitSha, loadSha } from "@/lib/projects/format";
import { githubQueue } from "@/lib/projects/queue";
import { projectKeys, useConnections, useOwner, useSavedKnowledge, useSavedSnapshot } from "@/lib/projects/use-projects";
import { PrivateChip, RepoName, ShaChip } from "./parts";
import { CardSkeleton, Crumbs, Notice, ProjectError } from "./shell";

type Confirm = "repository" | "installation" | null;

/** What Trace holds for a project, and the controls to stop access. Deleting stored data has no endpoint yet, and says so. */
export function ManageView({ connectionId }: { connectionId: string }) {
  const owner = useOwner();
  const router = useRouter();
  const queries = useQueryClient();
  const connections = useConnections();
  const project = connections.data?.find((item) => item.id === connectionId && item.status !== "disconnected");
  const sha = loadSha(connectionId);
  const snapshot = useSavedSnapshot(connectionId, sha);
  const knowledge = useSavedKnowledge(connectionId, sha);
  const [confirm, setConfirm] = useState<Confirm>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  if (connections.isPending) return <CardSkeleton count={2} />;
  if (connections.error) return <ProjectError error={connections.error} onRetry={() => void connections.refetch()} />;
  if (!project) return <Notice title="That project isn't connected" detail="It may already be disconnected, or it belongs to another account."><Link href="/projects" className="mt-5 inline-flex min-h-11 items-center rounded-[11px] bg-foreground px-5 font-medium text-white hover:bg-foreground/85">Back to projects</Link></Notice>;
  const installationId = project.installation_id;

  async function disconnect(kind: "repository" | "installation") {
    setBusy(true); setError(null);
    try {
      await githubQueue((): Promise<unknown> => kind === "repository" ? githubProjectsApi.disconnect(connectionId) : githubProjectsApi.disconnectInstallation(installationId));
      await queries.invalidateQueries({ queryKey: projectKeys.all(owner) });
      router.push("/projects");
    } catch (failure) { setError(failure); setBusy(false); }
  }

  const stats: [string, number | null][] = [
    ["Files listed", knowledge.data?.catalog.length ?? null],
    ["Files read", knowledge.data?.coverage.fetched_files ?? null],
    ["Excerpts kept", knowledge.data?.references.length ?? snapshot.data?.references.length ?? null],
    ["Commits seen", knowledge.data?.commits?.length ?? null],
  ];

  return (
    <div className="grid gap-8 pb-24">
      <Crumbs items={[{ label: "Projects", href: "/projects" }, { label: project.full_name, href: `/projects/${encodeURIComponent(connectionId)}` }, { label: "Manage" }]} />
      <div className="flex flex-wrap items-center gap-2"><RepoName fullName={project.full_name} className="max-w-[22rem] text-[0.9375rem] font-medium" /><PrivateChip isPrivate={project.private} />{isCommitSha(sha) && <ShaChip sha={sha} />}</div>

      <Enter>
        <section aria-labelledby="held-title" className="pj-card p-5 sm:p-6">
          <h2 id="held-title" className="text-[1.0625rem] font-semibold">What Trace has for this project</h2>
          {!isCommitSha(sha) ? <p className="mt-3 text-secondary">No commit is pinned in this browser, so there is nothing to count yet.</p> : (
            <>
              <dl className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4">
                {stats.map(([name, value]) => <div key={name} className="pj-stat"><dd className="text-[1.5rem] font-semibold tracking-[-0.03em] tabular-nums">{value === null ? "—" : <CountUp value={value} />}</dd><dt className="text-[0.8125rem] text-secondary">{name}</dt></div>)}
              </dl>
              <p className="mt-4 max-w-[64ch] text-[0.875rem] leading-relaxed text-secondary">Counts are for the commit pinned in this browser. Excerpts are sent to the AI provider only when you generate a learning path or ask the project tutor a question. A dash means that step hasn&apos;t run for this commit.</p>
            </>
          )}
        </section>
      </Enter>

      <Enter delay={80}>
        <section aria-labelledby="stop-title" className="pj-card p-5 sm:p-6">
          <h2 id="stop-title" className="text-[1.0625rem] font-semibold">Stop access</h2>
          <p className="mt-2 max-w-[64ch] text-[0.9375rem] leading-relaxed text-secondary">Disconnecting stops Trace from reading from GitHub. It keeps your private history and doesn&apos;t uninstall the GitHub App; you can remove the App on GitHub whenever you like.</p>
          <div className="mt-5 grid gap-4 md:grid-cols-2">
            <Choice title="Disconnect this repository" body="Trace stops using this one repository." open={confirm === "repository"} busy={busy} onOpen={() => setConfirm("repository")} onCancel={() => setConfirm(null)} onConfirm={() => void disconnect("repository")} confirmLabel="Yes, disconnect it" />
            <Choice title="Disconnect GitHub entirely" body="Trace stops using every repository from this installation." open={confirm === "installation"} busy={busy} onOpen={() => setConfirm("installation")} onCancel={() => setConfirm(null)} onConfirm={() => void disconnect("installation")} confirmLabel="Yes, disconnect everything" />
          </div>
          {error ? <ProjectError className="mt-4" error={error} /> : null}
        </section>
      </Enter>

      <Enter delay={140}>
        <section aria-labelledby="delete-title" className="pj-card p-5 sm:p-6">
          <h2 id="delete-title" className="text-[1.0625rem] font-semibold">Delete stored project data</h2>
          <p className="mt-2 max-w-[64ch] text-[0.9375rem] leading-relaxed text-secondary">Deleting what Trace saved (snapshots, excerpts, learning paths) isn&apos;t something this server offers yet, so there is no button for it. Disconnecting is the strongest control available today. We&apos;ve asked for a delete action; see the notes in the project&apos;s documentation.</p>
        </section>
      </Enter>
    </div>
  );
}

function Choice({ title, body, open, busy, onOpen, onCancel, onConfirm, confirmLabel }: { title: string; body: string; open: boolean; busy: boolean; onOpen: () => void; onCancel: () => void; onConfirm: () => void; confirmLabel: string }) {
  return (
    <div className="rounded-xl border border-border bg-surface-muted/50 p-4">
      <p className="font-medium">{title}</p>
      <p className="mt-1 text-[0.875rem] text-secondary">{body}</p>
      {open ? (
        <div role="group" aria-label={`Confirm: ${title}`} className="mt-4 flex flex-wrap items-center gap-3">
          <button type="button" disabled={busy} onClick={onConfirm} className="inline-flex min-h-11 items-center rounded-[11px] border border-error/40 bg-surface px-4 font-medium text-error hover:bg-error-soft disabled:opacity-50">{busy ? "Disconnecting…" : confirmLabel}</button>
          <button type="button" disabled={busy} onClick={onCancel} className="min-h-11 px-2 font-medium underline underline-offset-4">Keep it</button>
        </div>
      ) : <button type="button" onClick={onOpen} className="mt-4 inline-flex min-h-11 items-center rounded-[11px] border border-border-strong bg-surface px-4 font-medium hover:bg-surface-muted">{title}</button>}
    </div>
  );
}
