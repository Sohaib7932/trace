"use client";

import { useQuery } from "@tanstack/react-query";
import { GitBranch } from "lucide-react";
import Link from "next/link";
import { githubProjectsApi } from "@/lib/api/github-projects";
import { describeProjectError } from "@/lib/projects/errors";
import { githubQueue } from "@/lib/projects/queue";

/** A "GitHub" row for Settings: connected or not, with a link to manage it on Projects. Read-only here. */
export function GitHubSettings() {
  const installations = useQuery({ queryKey: ["account-github"], queryFn: ({ signal }) => githubQueue(githubProjectsApi.installations, signal), retry: false, staleTime: 30_000 });
  const active = installations.data?.filter((item) => item.status !== "disconnected") ?? [];
  const needsReconnect = active.some((item) => item.status === "reauthorization_required");
  const info = installations.error ? describeProjectError(installations.error) : null;
  return (
    <div className="dash-card flex flex-col">
      <h3 className="flex items-center gap-2 text-[0.9375rem] font-semibold"><span aria-hidden="true" className="acct-icon"><GitBranch className="size-4" strokeWidth={1.8} /></span>GitHub</h3>
      <p className="mt-3 text-[0.875rem] text-secondary">For learning from your own projects</p>
      <p className="mt-0.5 text-[0.9375rem]" aria-live="polite">
        {installations.isPending ? "Checking…"
          : info?.unavailable ? "Not enabled on this server yet"
          : info ? "Status unavailable right now"
          : active.length === 0 ? "Not connected"
          : needsReconnect ? "Connected, but GitHub access changed" : `Connected · ${active.length} ${active.length === 1 ? "installation" : "installations"}`}
      </p>
      {!info?.unavailable && !installations.isPending && (
        <p className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-[0.875rem] font-medium">
          <Link href={active.length === 0 || needsReconnect ? "/projects/connect" : "/projects"} className="inline-flex min-h-11 items-center underline underline-offset-4">{active.length === 0 ? "Connect GitHub" : needsReconnect ? "Reconnect" : "Open Projects"}</Link>
          {active.length > 0 && <Link href="/projects" className="inline-flex min-h-11 items-center underline underline-offset-4">Disconnect a repository</Link>}
        </p>
      )}
    </div>
  );
}
