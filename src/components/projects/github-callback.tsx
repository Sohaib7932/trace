"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ApiError } from "@/lib/api/client";
import { githubAuthorizationDiagnostic, PendingGitHubAuthorizationError, type GitHubAuthorizationDiagnostic, type GitHubAuthorizationPresence, type GitHubAuthorizationStage } from "@/lib/api/github-authorization-diagnostics";
import { clearGitHubAuthorization, githubAuthorizationUrl, githubProjectsApi, pendingGitHubAuthorization, saveGitHubAuthorization } from "@/lib/api/github-projects";

export function GitHubProjectCallback() {
  const started = useRef(false);
  const [message, setMessage] = useState("Checking GitHub authorization…");
  const [diagnostic, setDiagnostic] = useState<GitHubAuthorizationDiagnostic | null>(null);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const query = new URLSearchParams(window.location.search);
    const presence = {
      callback_state_present: Boolean(query.get("state")),
      callback_code_present: Boolean(query.get("code")),
      callback_installation_present: Boolean(query.get("installation_id")),
      provider_error_present: query.has("error"),
    };
    // Do not retain the one-time code in the address bar or navigation history.
    window.history.replaceState(null, "", "/projects/github/callback");
    void (async () => {
      let stage: GitHubAuthorizationStage = "callback_query";
      let pendingPresence: GitHubAuthorizationPresence = {};
      try {
        if (query.has("error")) { stage = "provider_declined"; throw new Error("GitHub authorization was not completed."); }
        const state = query.get("state") ?? "";
        const pending = pendingGitHubAuthorization(state);
        pendingPresence = { pending_present: true, saved_state_present: Boolean(pending.state), saved_expiry_present: Boolean(pending.expires_at), saved_authorization_url_present: Boolean(pending.authorization_url) };
        const code = query.get("code");
        if (!code) {
          stage = "installation_id_invalid";
          const installation = query.get("installation_id") ?? "";
          if (!/^[1-9][0-9]{0,14}$/.test(installation)) throw new Error("No selected installation was returned. Start again.");
          stage = "setup_storage";
          saveGitHubAuthorization({ ...pending, installation_id: Number(installation) });
          stage = "setup_navigation";
          window.location.assign(githubAuthorizationUrl(pending.authorization_url, "authorize"));
          return;
        }
        // An existing installation is discovered by the backend with the user's
        // OAuth token. A setup callback's ID is only an optional selection hint.
        stage = "completion_call"; // Invocation is not proof that a request reached the server.
        await githubProjectsApi.complete({ state, code, ...(pending.installation_id ? { installation_id: pending.installation_id } : {}) });
        stage = "pending_cleanup";
        clearGitHubAuthorization();
        stage = "return_navigation";
        window.location.replace("/projects");
      } catch (failure) {
        const pendingFailure = failure instanceof PendingGitHubAuthorizationError ? failure.diagnostic : null;
        setDiagnostic(githubAuthorizationDiagnostic(pendingFailure?.failure_stage ?? stage, { ...(pendingFailure ?? pendingPresence), ...presence }));
        // A blocked storage API must not hide the diagnostic or trigger a retry.
        try { clearGitHubAuthorization(); } catch { /* No state bypass or recovery. */ }
        const messages: Partial<Record<number, string>> = {
          401: "Sign in with the same Trace account, then start a fresh GitHub connection.",
          403: "GitHub access could not be verified. Check that your GitHub account can access the selected installation and its read-only repositories.",
          404: "No accessible installation was found for this GitHub App. Check the GitHub account you authorized. Install the App only if it is not already installed for that account.",
          409: "The connection state expired, was already used, or an installation could not be selected uniquely. Start a fresh connection. If it still fails and you have multiple installations, explicit installation selection is required.",
          429: "The connection request limit was reached. Wait before starting a fresh connection.",
          504: "GitHub authorization took too long. Return to Project Learning to check the current connection before starting again.",
        };
        setMessage((failure instanceof ApiError ? messages[failure.status] : undefined)
          ?? "GitHub connection could not be completed. Return to Project Learning, check the current connection and start again with the same Trace account. No successful connection is assumed.");
      }
    })();
  }, []);
  return <section className="py-12"><h1 className="type-h3">GitHub connection</h1><p role="status" className="mt-4">{message}</p>{diagnostic && <details className="mt-4"><summary>Connection diagnostics</summary><pre data-testid="github-authorization-diagnostic" className="mt-2 whitespace-pre-wrap text-xs">{JSON.stringify(diagnostic, null, 2)}</pre></details>}<Link href="/projects" className="mt-6 inline-block underline">Return to Project Learning</Link></section>;
}
