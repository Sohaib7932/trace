import { protectedApiRequest } from "./client";
import type { components } from "./schema";

export type GitHubInstallation = { installation_id: number; repository_selection: "selected"; authorization_expires_at: string | null; status?: "authorized" | "reauthorization_required" | "disconnected" };
export type GitHubRepository = { repository_id: number; full_name: string; private: boolean };
export type GitHubConnection = GitHubRepository & { id: string; installation_id: number; status?: "connected" | "disconnected" };
export type GitHubStart = { installation_url: string; authorization_url: string; state: string; expires_at: string };
export type ProjectSnapshot = {
  schema_version: "project-snapshot-v1"; connection_id: string; commit_sha: string; digest: string;
  references: { reference_id: string; kind: string; path: string; text: string }[];
  omitted_files: number; complete_repository: false;
};
export type ProjectLearningPath = {
  status: "ready" | "unavailable"; content: null | { schema_version: "project-learning-v1"; title: string; steps: { title: string; explanation: string; question: string; reference_ids: string[] }[] };
  snapshot_digest: string; commit_sha: string; source: "ai" | "test_fixture" | "none";
  grading: "ungraded"; execution_status: "not_executed"; can_complete_lesson: false;
};
export type RepositoryKnowledge = components["schemas"]["RepositoryKnowledgeSnapshot"];
export type ProjectAnswer = components["schemas"]["ProjectQuestionAnswer"];
export type ProjectQuestion = components["schemas"]["ProjectQuestionCreate"];
const prefix = "/projects/github";
export const githubProjectsApi = {
  start: () => protectedApiRequest<GitHubStart>(`${prefix}/installations/start`, {}),
  complete: (body: { installation_id: number; code: string; state: string }) => protectedApiRequest<GitHubInstallation>(`${prefix}/installations/complete`, body),
  installations: () => protectedApiRequest<GitHubInstallation[]>(`${prefix}/installations`),
  choices: (id: number) => protectedApiRequest<GitHubRepository[]>(`${prefix}/installations/${id}/repositories`),
  connect: (installation_id: number, repository_id: number) => protectedApiRequest<GitHubConnection>(`${prefix}/repositories`, { installation_id, repository_id }),
  connections: () => protectedApiRequest<GitHubConnection[]>(`${prefix}/repositories`),
  sync: (id: string, commit_sha: string) => protectedApiRequest<ProjectSnapshot>(`${prefix}/repositories/${encodeURIComponent(id)}/sync`, { commit_sha }),
  learningPath: (id: string, commit_sha: string) => protectedApiRequest<ProjectLearningPath>(`${prefix}/repositories/${encodeURIComponent(id)}/learning-path`, { commit_sha }),
  disconnect: (id: string) => protectedApiRequest<GitHubConnection>(`${prefix}/repositories/${encodeURIComponent(id)}/disconnect`, {}),
  disconnectInstallation: (id: number) => protectedApiRequest<GitHubInstallation>(`${prefix}/installations/${id}/disconnect`, {}),
  ingest: (id: string, commit_sha: string) => protectedApiRequest<RepositoryKnowledge>(`${prefix}/repositories/${encodeURIComponent(id)}/ingest`, { commit_sha }),
  knowledge: (id: string, commit_sha: string) => protectedApiRequest<RepositoryKnowledge>(`${prefix}/repositories/${encodeURIComponent(id)}/knowledge?commit_sha=${encodeURIComponent(commit_sha)}`),
  ask: (id: string, body: ProjectQuestion) => protectedApiRequest<ProjectAnswer>(`${prefix}/repositories/${encodeURIComponent(id)}/ask`, body),
};

const PENDING_KEY = "trace-github-app-authorization-v1";
type Pending = GitHubStart & { installation_id?: number };
export function githubAuthorizationUrl(value: string, kind: "install" | "authorize"): string {
  const url = new URL(value);
  if (url.protocol !== "https:" || url.hostname !== "github.com" || url.port || url.username || url.password || url.hash
    || !(kind === "authorize" ? url.pathname === "/login/oauth/authorize" : /^\/apps\/[a-z0-9-]+\/installations\/new$/.test(url.pathname))) {
    throw new Error("The GitHub authorization address could not be verified.");
  }
  return url.href;
}
export function saveGitHubAuthorization(value: Pending) { sessionStorage.setItem(PENDING_KEY, JSON.stringify(value)); }
export function clearGitHubAuthorization() { sessionStorage.removeItem(PENDING_KEY); }
export function pendingGitHubAuthorization(state: string): Pending {
  const value = JSON.parse(sessionStorage.getItem(PENDING_KEY) ?? "null") as Pending | null;
  if (!value || value.state !== state || !Number.isFinite(Date.parse(value.expires_at)) || Date.parse(value.expires_at) <= Date.now()) {
    throw new Error("GitHub authorization expired or belongs to another browser flow. Start again.");
  }
  githubAuthorizationUrl(value.authorization_url, "authorize");
  return value;
}
