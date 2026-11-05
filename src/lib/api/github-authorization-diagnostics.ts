/** Browser-only, value-free diagnostics. Never pass URLs, errors or credentials. */
const stages = [
  "start_request", "start_url_validation", "start_storage", "start_navigation",
  "callback_query", "provider_declined", "pending_read_failed", "pending_missing",
  "pending_json_invalid", "state_mismatch", "expiry_invalid", "expired",
  "authorization_url_invalid", "installation_id_invalid", "setup_storage",
  "setup_navigation", "completion_call", "pending_cleanup", "return_navigation",
  "unexpected",
] as const;
export type GitHubAuthorizationStage = typeof stages[number];
const presenceFields = [
  "start_state_present", "start_expiry_present", "start_authorization_url_present", "start_installation_url_present",
  "callback_state_present", "callback_code_present", "callback_installation_present",
  "provider_error_present", "pending_present", "saved_state_present",
  "saved_expiry_present", "saved_authorization_url_present",
] as const;
export type GitHubAuthorizationPresence = Partial<Record<typeof presenceFields[number], boolean>>;
export type GitHubAuthorizationDiagnostic = GitHubAuthorizationPresence & {
  version: 1; failure_stage: GitHubAuthorizationStage;
};

export function githubAuthorizationDiagnostic(
  stage: GitHubAuthorizationStage, presence: GitHubAuthorizationPresence,
): GitHubAuthorizationDiagnostic {
  const result: GitHubAuthorizationDiagnostic = {
    version: 1, failure_stage: stages.includes(stage) ? stage : "unexpected",
  };
  // Copy only exact boolean fields. Omitted means not observed, not absent.
  for (const key of presenceFields) if (typeof presence[key] === "boolean") result[key] = presence[key];
  return result;
}

export class PendingGitHubAuthorizationError extends Error {
  readonly diagnostic: GitHubAuthorizationDiagnostic;
  constructor(stage: GitHubAuthorizationStage, presence: GitHubAuthorizationPresence) {
    super("GitHub authorization expired or belongs to another browser flow. Start again.");
    this.diagnostic = githubAuthorizationDiagnostic(stage, presence);
  }
}
