"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Check, Search } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { Enter } from "./enter";
import { githubProjectsApi, type GitHubRepository } from "@/lib/api/github-projects";
import { isProjectsUnavailable } from "@/lib/projects/errors";
import { MAX_SELECTION } from "@/lib/projects/format";
import { githubQueue } from "@/lib/projects/queue";
import { projectKeys, useChoices, useConnections, useInstallations, useOwner } from "@/lib/projects/use-projects";
import { PrivateChip, RepoName } from "./parts";
import { CardSkeleton, Notice, ProjectError } from "./shell";

const PAGE = 30;
type Result = { repo: GitHubRepository; state: "waiting" | "adding" | "done" | "failed"; id?: string; error?: unknown };

export function ImportView({ installation: wanted }: { installation?: number }) {
  const owner = useOwner();
  const router = useRouter();
  const queries = useQueryClient();
  const installations = useInstallations();
  const connections = useConnections();
  const usable = installations.data?.filter((item) => item.status === "authorized") ?? [];
  const [picked, setPicked] = useState<number | null>(wanted ?? null);
  const installationId = usable.some((item) => item.installation_id === picked) ? picked : usable[0]?.installation_id ?? null;
  const choices = useChoices(installationId);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [search, setSearch] = useState("");
  const [privateOnly, setPrivateOnly] = useState(false);
  const [shown, setShown] = useState(PAGE);
  const [results, setResults] = useState<Result[] | null>(null);
  const [running, setRunning] = useState(false);

  const added = useMemo(() => new Set((connections.data ?? []).filter((item) => item.status !== "disconnected").map((item) => item.repository_id)), [connections.data]);
  const visible = useMemo(() => {
    const term = search.trim().toLowerCase();
    return (choices.data ?? []).filter((repo) => (!term || repo.full_name.toLowerCase().includes(term)) && (!privateOnly || repo.private));
  }, [choices.data, search, privateOnly]);

  const failure = installations.error ?? connections.error;
  if (failure && isProjectsUnavailable(failure)) return <ProjectError error={failure} />;
  if (!installations.data || !connections.data) return failure ? <ProjectError error={failure} onRetry={() => { void installations.refetch(); void connections.refetch(); }} /> : <CardSkeleton count={3} />;
  if (failure) return <ProjectError error={failure} onRetry={() => { void installations.refetch(); void connections.refetch(); }} />;
  if (usable.length === 0) {
    const needsReconnect = installations.data.some((item) => item.status === "reauthorization_required");
    return (
      <Notice title={needsReconnect ? "Reconnect GitHub to continue" : "Connect GitHub first"} detail={needsReconnect ? "GitHub access changed, so Trace needs you to approve it again before it can list repositories." : "Trace can only list repositories after you connect the GitHub App and choose which ones it may see."}>
        <Link href="/projects/connect" className="mt-5 inline-flex min-h-11 items-center rounded-[11px] bg-foreground px-5 font-medium text-white hover:bg-foreground/85">{needsReconnect ? "Reconnect GitHub" : "Connect GitHub"}</Link>
      </Notice>
    );
  }

  function toggle(repo: GitHubRepository) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(repo.repository_id)) next.delete(repo.repository_id);
      else if (next.size < MAX_SELECTION) next.add(repo.repository_id);
      return next;
    });
  }

  async function addAll(only?: Result[]) {
    if (installationId === null) return;
    const repos = only ? only.map((item) => item.repo) : (choices.data ?? []).filter((repo) => selected.has(repo.repository_id));
    if (repos.length === 0) return;
    const list: Result[] = repos.map((repo) => ({ repo, state: "waiting" }));
    setResults(list); setRunning(true);
    const update = (index: number, patch: Partial<Result>) => setResults((current) => current && current.map((item, position) => position === index ? { ...item, ...patch } : item));
    const done: Result[] = [];
    for (let index = 0; index < list.length; index += 1) {
      update(index, { state: "adding" });
      try {
        // One repository per request, one after another: the server allows one GitHub call at a time per account.
        const connection = await githubQueue(() => githubProjectsApi.connect(installationId, list[index].repo.repository_id));
        update(index, { state: "done", id: connection.id });
        done.push({ ...list[index], state: "done", id: connection.id });
      } catch (error) {
        update(index, { state: "failed", error });
      }
    }
    await queries.invalidateQueries({ queryKey: projectKeys.connections(owner) });
    setRunning(false);
    if (done.length === list.length && done.length === 1 && done[0].id) router.push(`/projects/${encodeURIComponent(done[0].id)}`);
  }

  if (results) {
    const finished = !running;
    const ok = results.filter((item) => item.state === "done");
    const bad = results.filter((item) => item.state === "failed");
    return (
      <Enter>
        <section aria-labelledby="added-title" className="pj-card p-6 sm:p-8">
          <h2 id="added-title" className="type-h3">{finished ? (bad.length ? "Some repositories need attention" : "Repositories added") : "Adding repositories…"}</h2>
          <ul aria-live="polite" className="mt-5 grid grid-cols-[minmax(0,1fr)] gap-2">
            {results.map((item) => (
              <li key={item.repo.repository_id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border px-4 py-3">
                <span className="min-w-0 flex-1"><RepoName fullName={item.repo.full_name} /></span>
                <span className="text-[0.875rem]">
                  {item.state === "waiting" && <span className="text-secondary">Waiting</span>}
                  {item.state === "adding" && <span className="text-secondary">Adding…</span>}
                  {item.state === "done" && item.id && <Link href={`/projects/${encodeURIComponent(item.id)}`} className="inline-flex items-center gap-1 font-medium text-success"><Check aria-hidden="true" className="size-4" strokeWidth={2.4} />Added · Open</Link>}
                  {item.state === "failed" && <span className="font-medium text-error">Not added</span>}
                </span>
              </li>
            ))}
          </ul>
          {bad.map((item) => <ProjectError key={item.repo.repository_id} className="mt-4" error={item.error} />)}
          {finished && (
            <div className="mt-6 flex flex-wrap gap-3">
              {bad.length > 0 && <button type="button" onClick={() => void addAll(bad)} className="inline-flex min-h-11 items-center rounded-[11px] bg-foreground px-5 font-medium text-white hover:bg-foreground/85">Try the failed ones again</button>}
              <Link href="/projects" className="inline-flex min-h-11 items-center rounded-[11px] border border-border-strong px-5 font-medium hover:bg-surface-muted">{ok.length > 0 ? "See my projects" : "Back to projects"}</Link>
              <button type="button" onClick={() => { setResults(null); setSelected(new Set()); }} className="min-h-11 px-2 font-medium underline underline-offset-4">Choose more</button>
            </div>
          )}
        </section>
      </Enter>
    );
  }

  return (
    <div className="pb-28">
      {usable.length > 1 && (
        <div role="radiogroup" aria-label="GitHub installation" className="mb-5 flex flex-wrap gap-2">
          {usable.map((item) => (
            <button key={item.installation_id} type="button" role="radio" aria-checked={item.installation_id === installationId} onClick={() => { setPicked(item.installation_id); setSelected(new Set()); setShown(PAGE); }} className="pj-seg" data-on={item.installation_id === installationId ? "" : undefined}>Installation <span className="pj-mono">#{item.installation_id}</span></button>
          ))}
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
        <label className="pj-search">
          <Search aria-hidden="true" className="size-4 text-secondary" strokeWidth={1.8} />
          <span className="sr-only">Search repositories</span>
          <input value={search} onChange={(event) => { setSearch(event.target.value); setShown(PAGE); }} placeholder="Search repositories" autoComplete="off" spellCheck={false} />
        </label>
        <button type="button" role="switch" aria-checked={privateOnly} onClick={() => { setPrivateOnly(!privateOnly); setShown(PAGE); }} className="pj-seg" data-on={privateOnly ? "" : undefined}>Private only</button>
      </div>

      <p className="mt-4 max-w-[70ch] text-[0.875rem] leading-relaxed text-secondary">
        Trace skips secrets, <span className="pj-mono">.env</span> files, keys, binaries and very large files. You&apos;ll see exactly what was skipped after the repository is read.
      </p>

      {choices.isPending ? <div className="mt-6"><CardSkeleton count={4} /></div> : choices.error ? <ProjectError className="mt-6" error={choices.error} onRetry={() => void choices.refetch()} /> : (
        <>
          <p aria-live="polite" className="mt-5 text-[0.8125rem] text-secondary">{visible.length} {visible.length === 1 ? "repository" : "repositories"} shown{choices.data.length !== visible.length ? ` of ${choices.data.length}` : ""}</p>
          {choices.data.length === 0 ? (
            <Notice title="No repositories shared with the App" detail="On GitHub, open the App's settings and choose at least one repository for it to see, then come back here." />
          ) : visible.length === 0 ? <p className="mt-6 text-secondary">Nothing matches that search.</p> : (
            <ul className="mt-3 grid grid-cols-[minmax(0,1fr)] gap-2">
              {visible.slice(0, shown).map((repo) => {
                const already = added.has(repo.repository_id);
                const checked = selected.has(repo.repository_id);
                const full = !checked && selected.size >= MAX_SELECTION;
                return (
                  <li key={repo.repository_id}>
                    <label className="pj-row" data-checked={checked ? "" : undefined} data-disabled={already || full ? "" : undefined}>
                      <input type="checkbox" checked={checked} disabled={already || full} onChange={() => toggle(repo)} />
                      <span aria-hidden="true" className="pj-box"><Check className="size-3.5" strokeWidth={3} /></span>
                      <span className="min-w-0 flex-1"><RepoName fullName={repo.full_name} /></span>
                      <PrivateChip isPrivate={repo.private} />
                      {already && <span className="pj-chip pj-status pj-status-ok">Already added</span>}
                    </label>
                  </li>
                );
              })}
            </ul>
          )}
          {visible.length > shown && <button type="button" onClick={() => setShown(shown + PAGE)} className="mt-4 min-h-11 font-medium underline underline-offset-4">Show more</button>}
        </>
      )}

      <div className="pj-actionbar" role="region" aria-label="Selection">
        <p className="text-[0.9375rem]"><span key={selected.size} className="pj-pop font-semibold tabular-nums">{selected.size}</span> selected <span className="text-secondary">· read-only · up to {MAX_SELECTION} at a time</span></p>
        <button type="button" disabled={selected.size === 0 || running} onClick={() => void addAll()} className="inline-flex min-h-11 items-center gap-2 rounded-[11px] bg-foreground px-5 font-medium text-white transition hover:bg-foreground/85 disabled:cursor-not-allowed disabled:opacity-45">
          Add selected<ArrowRight aria-hidden="true" className="size-4" strokeWidth={1.8} />
        </button>
      </div>
    </div>
  );
}
