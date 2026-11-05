"use client";

import { ArrowRight, GitBranch, Plus, Settings2 } from "lucide-react";
import Link from "next/link";
import { Enter } from "./enter";
import type { GitHubConnection, GitHubInstallation } from "@/lib/api/github-projects";
import { isProjectsUnavailable } from "@/lib/projects/errors";
import { useConnections, useInstallations } from "@/lib/projects/use-projects";
import { PrivateChip, RepoName, StatusChip } from "./parts";
import { CardSkeleton, EmptyArt, ProjectError } from "./shell";
import { TraceFlow } from "./trace-flow";

const DEMO = process.env.NEXT_PUBLIC_PROJECTS_DEMO === "1";

function installationStatus(installation: GitHubInstallation) {
  if (installation.status === "disconnected") return <StatusChip tone="off">Disconnected</StatusChip>;
  if (installation.status === "reauthorization_required") return <StatusChip tone="warn">Reconnect needed</StatusChip>;
  return <StatusChip tone="ok">Connected</StatusChip>;
}

export function ProjectsHub() {
  const installations = useInstallations();
  const connections = useConnections();
  const failure = installations.error ?? connections.error;
  if (failure && isProjectsUnavailable(failure)) return <ProjectError error={failure} />;
  if (!installations.data || !connections.data) {
    return failure ? <ProjectError error={failure} onRetry={() => { void installations.refetch(); void connections.refetch(); }} /> : <CardSkeleton count={3} />;
  }
  if (failure) return <ProjectError error={failure} onRetry={() => { void installations.refetch(); void connections.refetch(); }} />;

  const active = installations.data.filter((item) => item.status !== "disconnected");
  const live = connections.data.filter((item) => item.status !== "disconnected");

  if (active.length === 0) {
    return (
      <div className="grid gap-8">
        <Enter>
          <section className="pj-card overflow-hidden p-6 sm:p-9">
            <div className="grid items-center gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
              <div>
                <p className="pj-eyebrow">Step 1</p>
                <h2 className="type-h3 mt-2">Connect GitHub</h2>
                <p className="mt-3 max-w-[46ch] leading-relaxed text-secondary">
                  Choose the repositories you want to learn from. Trace reads them read-only, picks short excerpts, and turns them into questions about your own code.
                </p>
                <Link href="/projects/connect" className="mt-6 inline-flex min-h-11 items-center gap-2 rounded-[11px] bg-[linear-gradient(180deg,#ff934f,#ff7a2e)] px-5 font-semibold text-foreground shadow-[inset_0_1px_0_rgba(255,255,255,0.45),0_6px_16px_-6px_rgba(232,116,59,0.7)] hover:brightness-105">
                  Connect GitHub<ArrowRight aria-hidden="true" className="size-4" strokeWidth={1.8} />
                </Link>
              </div>
              <TraceFlow className="w-full" />
            </div>
          </section>
        </Enter>
        {live.length > 0 && <Projects items={live} />}
        {DEMO && <DemoCard />}
      </div>
    );
  }

  return (
    <div className="grid gap-10">
      <Enter>
        <section aria-labelledby="gh-title" className="pj-card p-5 sm:p-6">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <h2 id="gh-title" className="text-[1.0625rem] font-semibold">GitHub</h2>
              <p className="mt-1 text-[0.875rem] text-secondary">Read-only access to the repositories you chose. You can disconnect at any time.</p>
            </div>
            <Link href="/projects/import" className="inline-flex min-h-11 items-center gap-2 rounded-[11px] bg-foreground px-5 font-medium text-white hover:bg-foreground/85"><Plus aria-hidden="true" className="size-4" strokeWidth={2} />Add repositories</Link>
          </div>
          <ul className="mt-4 grid gap-2">
            {active.map((installation) => (
              <li key={installation.installation_id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-surface-muted/60 px-4 py-3">
                <span className="flex items-center gap-3 text-[0.9375rem]"><GitBranch aria-hidden="true" className="size-4 text-secondary" strokeWidth={1.8} />GitHub App installation <span className="pj-mono text-secondary">#{installation.installation_id}</span></span>
                <span className="flex items-center gap-3">
                  {installationStatus(installation)}
                  {installation.status === "reauthorization_required"
                    ? <Link href="/projects/connect" className="text-[0.875rem] font-medium underline underline-offset-4">Reconnect</Link>
                    : <Link href={`/projects/import?installation=${installation.installation_id}`} className="text-[0.875rem] font-medium underline underline-offset-4">Choose repositories</Link>}
                </span>
              </li>
            ))}
          </ul>
        </section>
      </Enter>
      {live.length > 0 ? <Projects items={live} /> : (
        <Notice2 />
      )}
      {DEMO && <DemoCard />}
    </div>
  );
}

function Notice2() {
  return (
    <section className="pj-card p-8 text-center">
      <EmptyArt className="mx-auto mb-4 h-24 w-44" />
      <h2 className="type-h3">No repositories yet</h2>
      <p className="mx-auto mt-2 max-w-[46ch] text-secondary">Pick one small repository to start. Trace only reads what you choose.</p>
      <Link href="/projects/import" className="mt-5 inline-flex min-h-11 items-center rounded-[11px] bg-foreground px-5 font-medium text-white hover:bg-foreground/85">Choose repositories</Link>
    </section>
  );
}

function Projects({ items }: { items: GitHubConnection[] }) {
  return (
    <section aria-labelledby="projects-title">
      <h2 id="projects-title" className="type-h3">Your projects</h2>
      <div className="mt-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {items.map((project, index) => <ProjectCard key={project.id} project={project} index={index} />)}
      </div>
    </section>
  );
}

function ProjectCard({ project, index }: { project: GitHubConnection; index: number }) {
  return (
    <Enter delay={index * 90} className="min-w-0">
      <article className="pj-card pj-lift flex h-full flex-col p-5">
        <div className="flex items-start justify-between gap-3">
          <span aria-hidden="true" className="pj-icon"><GitBranch className="size-4" strokeWidth={1.8} /></span>
          <PrivateChip isPrivate={project.private} />
        </div>
        <h3 className="mt-3 text-[1.0625rem] font-semibold tracking-[-0.01em]"><RepoName fullName={project.full_name} /></h3>
        <p className="mt-1 text-[0.8125rem] text-secondary">Pick a commit, let Trace read it, then follow the learning path.</p>
        <div className="mt-auto flex flex-wrap items-center justify-between gap-x-4 gap-y-1 pt-5">
          <StatusChip tone="ok">Connected</StatusChip>
          <span className="flex items-center gap-4">
            <Link href={`/projects/${encodeURIComponent(project.id)}/manage`} aria-label={`Manage ${project.full_name}`} className="inline-flex min-h-11 items-center gap-1.5 text-[0.9375rem] font-medium text-secondary underline-offset-4 hover:text-foreground hover:underline"><Settings2 aria-hidden="true" className="size-4" strokeWidth={1.8} />Manage</Link>
            <Link href={`/projects/${encodeURIComponent(project.id)}`} aria-label={`Open ${project.full_name}`} className="inline-flex min-h-11 items-center gap-1.5 text-[0.9375rem] font-medium">Open<ArrowRight aria-hidden="true" className="size-4" strokeWidth={1.8} /></Link>
          </span>
        </div>
      </article>
    </Enter>
  );
}

function DemoCard() {
  return (
    <section aria-label="Demo project" className="pj-card p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div><span className="pj-chip">Demo</span><h3 className="mt-2 font-semibold">Sample project</h3><p className="text-[0.875rem] text-secondary">Made-up data so you can see the screens. Nothing here comes from GitHub.</p></div>
        <Link href="/projects/demo" className="inline-flex min-h-11 items-center rounded-[11px] border border-border-strong px-5 font-medium hover:bg-surface-muted">See the demo</Link>
      </div>
    </section>
  );
}

