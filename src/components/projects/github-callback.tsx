"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { ApiError } from "@/lib/api/client";
import { githubAuthorizationDiagnostic, PendingGitHubAuthorizationError, type GitHubAuthorizationDiagnostic, type GitHubAuthorizationPresence, type GitHubAuthorizationStage } from "@/lib/api/github-authorization-diagnostics";
import { clearGitHubAuthorization, githubAuthorizationUrl, githubProjectsApi, pendingGitHubAuthorization, saveGitHubAuthorization } from "@/lib/api/github-projects";
import { describeProjectError, type ProjectErrorInfo } from "@/lib/projects/errors";
import { githubQueue } from "@/lib/projects/queue";
import { useAuth } from "@/lib/supabase/use-auth";
import { PipelineTracker, type Stage } from "./parts";
import { ProjectError } from "./shell";

type Phase = "working" | "redirecting" | "success" | "cancelled" | "signed-out" | "failed";
type Query = { state: string; code: string | null; installation: string | null; declined: boolean; present: GitHubAuthorizationPresence };

/**
 * Finishes the GitHub connection. The one-time parameters GitHub added to the address are read once,
 * removed from the address bar straight away, kept only in memory, and sent to our backend once.
 * They are never logged or shown.
 */
export function GitHubProjectCallback() {
  const auth = useAuth();
  const query = useRef<Query | null>(null);
  const started = useRef(false);
  const [phase, setPhase] = useState<Phase>("working");
  const [info, setInfo] = useState<ProjectErrorInfo | null>(null);
  const [diagnostic, setDiagnostic] = useState<GitHubAuthorizationDiagnostic | null>(null);

  // Read and clear the address once (this effect runs twice in React strict mode; the ref makes the second run a no-op).
  useEffect(() => {
    if (query.current) return;
    const params = new URLSearchParams(window.location.search);
    query.current = {
      state: params.get("state") ?? "",
      code: params.get("code"),
      installation: params.get("installation_id"),
      declined: params.has("error"),
      present: {
        callback_state_present: Boolean(params.get("state")),
        callback_code_present: Boolean(params.get("code")),
        callback_installation_present: Boolean(params.get("installation_id")),
        provider_error_present: params.has("error"),
      },
    };
    window.history.replaceState(null, "", "/projects/github/callback");
  }, []);

  useEffect(() => {
    const current = query.current;
    if (!current || auth.status === "loading" || started.current) return;
    if (auth.status !== "signed-in") {
      // GitHub's code works once and can't be kept safely across a sign-in page, so the connection restarts after signing in.
      started.current = true;
      queueMicrotask(() => setPhase("signed-out"));
      return;
    }
    started.current = true;
    let timer: number | undefined;
    void (async () => {
      let stage: GitHubAuthorizationStage = "callback_query";
      let pendingPresence: GitHubAuthorizationPresence = {};
      try {
        if (current.declined) { stage = "provider_declined"; setPhase("cancelled"); return; }
        const pending = pendingGitHubAuthorization(current.state);
        pendingPresence = { pending_present: true, saved_state_present: Boolean(pending.state), saved_expiry_present: Boolean(pending.expires_at), saved_authorization_url_present: Boolean(pending.authorization_url) };
        if (!current.code) {
          // Back from installing the App: GitHub still needs the person to approve the connection.
          stage = "installation_id_invalid";
          if (!current.installation || !/^[1-9][0-9]{0,14}$/.test(current.installation)) throw new Error("no_installation");
          stage = "setup_storage";
          saveGitHubAuthorization({ ...pending, installation_id: Number(current.installation) });
          stage = "setup_navigation";
          setPhase("redirecting");
          window.location.assign(githubAuthorizationUrl(pending.authorization_url, "authorize"));
          return;
        }
        stage = "completion_call";
        const code = current.code;
        await githubQueue(() => githubProjectsApi.complete({ state: current.state, code, ...(pending.installation_id ? { installation_id: pending.installation_id } : {}) }));
        stage = "pending_cleanup";
        clearGitHubAuthorization();
        stage = "return_navigation";
        setPhase("success");
        timer = window.setTimeout(() => window.location.replace("/projects/import"), 1400);
      } catch (failure) {
        const pendingFailure = failure instanceof PendingGitHubAuthorizationError ? failure.diagnostic : null;
        setDiagnostic(githubAuthorizationDiagnostic(pendingFailure?.failure_stage ?? stage, { ...(pendingFailure ?? pendingPresence), ...current.present }));
        try { clearGitHubAuthorization(); } catch { /* storage blocked: the diagnostic above is still shown */ }
        if (failure instanceof ApiError) setInfo(describeProjectError(failure));
        else setInfo({
          title: failure instanceof PendingGitHubAuthorizationError ? "This connection attempt expired" : "GitHub didn't send back what Trace needs",
          detail: "The connection has to start and finish in the same browser, within a few minutes. Start a fresh one.",
          action: { label: "Start again", href: "/projects/connect" }, requestId: null,
        });
        setPhase("failed");
      }
    })();
    return () => { if (timer) window.clearTimeout(timer); };
  }, [auth.status]);

  const stages: Stage[] = [
    { id: "return", label: "Back from GitHub", detail: "Your approval arrived.", state: "done" },
    { id: "check", label: "Checking the request", detail: "Matching it to this browser.", state: phase === "working" ? "active" : phase === "failed" || phase === "cancelled" || phase === "signed-out" ? "failed" : "done" },
    { id: "link", label: "Linking your account", detail: "Trace saves which repositories you allowed.", state: phase === "success" ? "done" : phase === "redirecting" || phase === "working" ? "todo" : "todo" },
  ];

  return (
    <section aria-labelledby="callback-title" className="pj-card mx-auto mt-10 max-w-[40rem] p-6 sm:p-8">
      <h1 id="callback-title" className="type-h3">Connecting GitHub</h1>
      <div className="mt-5"><PipelineTracker stages={stages} /></div>

      <div aria-live="polite" className="mt-6">
        {phase === "working" && <p role="status" className="text-secondary">Finishing the connection. This takes a few seconds.</p>}
        {phase === "redirecting" && <p role="status" className="text-secondary">Opening GitHub to confirm access…</p>}
        {phase === "success" && (
          <div role="status">
            <p className="font-medium text-success">GitHub is connected.</p>
            <p className="mt-1 text-secondary">Taking you to choose repositories…</p>
            <Link href="/projects/import" className="mt-3 inline-flex min-h-11 items-center rounded-[11px] bg-foreground px-5 font-medium text-white hover:bg-foreground/85">Choose repositories now</Link>
          </div>
        )}
        {phase === "cancelled" && (
          <div role="status">
            <p className="font-medium">You stopped before finishing on GitHub.</p>
            <p className="mt-1 text-secondary">Nothing was connected and nothing was read. You can try again whenever you like.</p>
            <Link href="/projects/connect" className="mt-3 inline-flex min-h-11 items-center rounded-[11px] bg-foreground px-5 font-medium text-white hover:bg-foreground/85">Connect again</Link>
          </div>
        )}
        {phase === "signed-out" && (
          <div role="status">
            <p className="font-medium">Sign in to finish connecting.</p>
            <p className="mt-1 text-secondary">GitHub&apos;s one-time approval can&apos;t be kept safely while you sign in, so you&apos;ll restart the connection afterwards. It takes a moment.</p>
            <Link href="/sign-in?next=%2Fprojects%2Fconnect" className="mt-3 inline-flex min-h-11 items-center rounded-[11px] bg-foreground px-5 font-medium text-white hover:bg-foreground/85">Sign in</Link>
          </div>
        )}
        {phase === "failed" && info && <ProjectError info={info} />}
      </div>

      {diagnostic && (
        <details className="mt-5 text-[0.8125rem] text-secondary">
          <summary className="cursor-pointer select-none">Connection details</summary>
          <pre data-testid="github-authorization-diagnostic" className="mt-1.5 text-xs whitespace-pre-wrap">{JSON.stringify(diagnostic, null, 2)}</pre>
        </details>
      )}
    </section>
  );
}
