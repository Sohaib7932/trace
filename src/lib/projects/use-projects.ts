"use client";

import { useQuery } from "@tanstack/react-query";
import { ApiError } from "@/lib/api/client";
import { githubProjectsApi } from "@/lib/api/github-projects";
import { useAuth } from "@/lib/supabase/use-auth";
import { isCommitSha } from "./format";
import { githubQueue } from "./queue";

/** The signed-in account id, or null. Every cache key includes it so accounts never share data. */
export function useOwner(): string | null {
  const auth = useAuth();
  return auth.status === "signed-in" ? auth.userId ?? "account" : null;
}

export const isNotFound = (error: unknown) => error instanceof ApiError && error.status === 404;

export const projectKeys = {
  all: (owner: string | null) => ["projects", owner] as const,
  installations: (owner: string | null) => ["projects", owner, "installations"] as const,
  connections: (owner: string | null) => ["projects", owner, "connections"] as const,
  choices: (owner: string | null, installation: number) => ["projects", owner, "choices", installation] as const,
  snapshot: (owner: string | null, id: string, sha: string) => ["projects", owner, "snapshot", id, sha] as const,
  knowledge: (owner: string | null, id: string, sha: string) => ["projects", owner, "knowledge", id, sha] as const,
  path: (owner: string | null, id: string, sha: string) => ["projects", owner, "path", id, sha] as const,
};

export function useInstallations() {
  const owner = useOwner();
  return useQuery({ queryKey: projectKeys.installations(owner), queryFn: ({ signal }) => githubQueue(githubProjectsApi.installations, signal), enabled: Boolean(owner), retry: false });
}

export function useConnections() {
  const owner = useOwner();
  return useQuery({ queryKey: projectKeys.connections(owner), queryFn: ({ signal }) => githubQueue(githubProjectsApi.connections, signal), enabled: Boolean(owner), retry: false });
}

export function useChoices(installation: number | null) {
  const owner = useOwner();
  return useQuery({
    queryKey: projectKeys.choices(owner, installation ?? 0),
    queryFn: ({ signal }) => githubQueue(() => githubProjectsApi.choices(installation!), signal),
    enabled: Boolean(owner) && installation !== null,
    retry: false,
  });
}

/** Saved results for one repository and pinned commit. A 404 means "not done yet", not a failure. */
export function useSavedSnapshot(connectionId: string, sha: string) {
  const owner = useOwner();
  return useQuery({ queryKey: projectKeys.snapshot(owner, connectionId, sha), queryFn: ({ signal }) => githubQueue(() => githubProjectsApi.snapshot(connectionId, sha), signal), enabled: Boolean(owner) && isCommitSha(sha), retry: false });
}
export function useSavedKnowledge(connectionId: string, sha: string) {
  const owner = useOwner();
  return useQuery({ queryKey: projectKeys.knowledge(owner, connectionId, sha), queryFn: ({ signal }) => githubQueue(() => githubProjectsApi.knowledge(connectionId, sha), signal), enabled: Boolean(owner) && isCommitSha(sha), retry: false });
}
export function useSavedPath(connectionId: string, sha: string) {
  const owner = useOwner();
  return useQuery({ queryKey: projectKeys.path(owner, connectionId, sha), queryFn: ({ signal }) => githubQueue(() => githubProjectsApi.savedLearningPath(connectionId, sha), signal), enabled: Boolean(owner) && isCommitSha(sha), retry: false });
}
