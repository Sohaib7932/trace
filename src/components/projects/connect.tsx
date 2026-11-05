"use client";

import { Ban, Check, Eye, ShieldCheck, Sparkles, Trash2 } from "lucide-react";
import { useState } from "react";
import { Enter } from "./enter";
import { githubAuthorizationDiagnostic, type GitHubAuthorizationDiagnostic, type GitHubAuthorizationPresence, type GitHubAuthorizationStage } from "@/lib/api/github-authorization-diagnostics";
import { githubAuthorizationUrl, githubProjectsApi, saveGitHubAuthorization } from "@/lib/api/github-projects";
import { isProjectsUnavailable } from "@/lib/projects/errors";
import { githubQueue } from "@/lib/projects/queue";
import { useInstallations } from "@/lib/projects/use-projects";
import { ProjectError } from "./shell";
import { TraceFlow } from "./trace-flow";

const POINTS = [
  { icon: Eye, title: "What Trace reads", body: "Only the repositories you choose, with read-only access. Nothing else on your GitHub account." },
  { icon: Sparkles, title: "What goes to the AI", body: "Short code excerpts picked from your chosen repository, so it can write questions and answers about them." },
  { icon: Ban, title: "What is never read", body: "Secrets, .env files, keys, binaries and very large files are skipped." },
  { icon: Trash2, title: "How to leave", body: "Disconnect a repository or the whole connection at any time from the project's Manage page." },
] as const;

export function ConnectView() {
  const installations = useInstallations();
  const [agreed, setAgreed] = useState(false);
  const [busy, setBusy] = useState<"install" | "authorize" | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [diagnostic, setDiagnostic] = useState<GitHubAuthorizationDiagnostic | null>(null);
  const hasInstallation = installations.data?.some((item) => item.status !== "disconnected") ?? false;

  async function go(kind: "install" | "authorize") {
    setError(null); setDiagnostic(null); setBusy(kind);
    let stage: GitHubAuthorizationStage = "start_request";
    const presence: GitHubAuthorizationPresence = {};
    try {
      // Our backend builds the GitHub address and the one-time state; the browser only follows it.
      const start = await githubQueue(githubProjectsApi.start);
      presence.start_state_present = Boolean(start.state);
      presence.start_expiry_present = Boolean(start.expires_at);
      presence.start_authorization_url_present = Boolean(start.authorization_url);
      presence.start_installation_url_present = Boolean(start.installation_url);
      stage = "start_url_validation";
      const authorize = githubAuthorizationUrl(start.authorization_url, "authorize");
      const install = githubAuthorizationUrl(start.installation_url, "install");
      stage = "start_storage";
      saveGitHubAuthorization(start);
      stage = "start_navigation";
      window.location.assign(kind === "authorize" ? authorize : install);
    } catch (failure) {
      setDiagnostic(githubAuthorizationDiagnostic(stage, presence));
      setError(failure);
      setBusy(null);
    }
  }

  if (installations.error && isProjectsUnavailable(installations.error)) return <ProjectError error={installations.error} />;
  const primary: "install" | "authorize" = hasInstallation ? "authorize" : "install";
  const other = primary === "install" ? "authorize" : "install";

  return (
    <div className="grid items-start gap-8 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)]">
      <Enter>
        <section aria-labelledby="consent-title" className="pj-card pj-glass p-6 sm:p-8">
          <div className="flex items-center gap-3">
            <span aria-hidden="true" className="pj-icon"><ShieldCheck className="size-4" strokeWidth={1.8} /></span>
            <h2 id="consent-title" className="text-[1.125rem] font-semibold tracking-[-0.015em]">Before you connect</h2>
          </div>
          <ul className="mt-5 grid gap-4">
            {POINTS.map(({ icon: Icon, title, body }) => (
              <li key={title} className="flex gap-3">
                <span aria-hidden="true" className="mt-0.5 text-primary-ink"><Icon className="size-[18px]" strokeWidth={1.8} /></span>
                <div><p className="font-medium">{title}</p><p className="mt-0.5 text-[0.9375rem] leading-relaxed text-secondary">{body}</p></div>
              </li>
            ))}
          </ul>

          <label className="pj-check mt-6">
            <input type="checkbox" checked={agreed} onChange={(event) => setAgreed(event.target.checked)} />
            <span aria-hidden="true" className="pj-box"><Check className="size-3.5" strokeWidth={3} /></span>
            <span>I understand what Trace reads and what it sends to the AI.</span>
          </label>

          <div className="mt-5 flex flex-wrap items-center gap-3">
            <button type="button" disabled={!agreed || busy !== null} onClick={() => void go(primary)} className="inline-flex min-h-11 items-center gap-2 rounded-[11px] bg-[linear-gradient(180deg,#ff934f,#ff7a2e)] px-5 font-semibold text-foreground shadow-[inset_0_1px_0_rgba(255,255,255,0.45),0_6px_16px_-6px_rgba(232,116,59,0.7)] transition disabled:cursor-not-allowed disabled:opacity-45">
              {busy ? "Opening GitHub…" : "Continue to GitHub"}
            </button>
            <button type="button" disabled={!agreed || busy !== null} onClick={() => void go(other)} className="inline-flex min-h-11 items-center rounded-[11px] border border-border-strong bg-surface px-4 text-[0.9375rem] font-medium hover:bg-surface-muted disabled:cursor-not-allowed disabled:opacity-45">
              {other === "authorize" ? "Already installed? Sign in with GitHub" : "Change which repositories the App can see"}
            </button>
          </div>
          <p className="mt-3 text-[0.8125rem] text-secondary" role="status">{agreed ? "GitHub opens next. It asks you to choose repositories and approve read-only access." : "Tick the box to continue."}</p>

          {error ? <ProjectError className="mt-5" error={error} onRetry={() => void go(primary)} /> : null}
          {diagnostic && (
            <details className="mt-4 text-[0.8125rem] text-secondary">
              <summary className="cursor-pointer select-none">Connection details</summary>
              <pre data-testid="github-authorization-diagnostic" className="mt-1.5 text-xs whitespace-pre-wrap">{JSON.stringify(diagnostic, null, 2)}</pre>
            </details>
          )}
        </section>
      </Enter>

      <Enter delay={120}>
        <section aria-label="How it works" className="pj-card p-6 sm:p-7">
          <TraceFlow className="w-full" />
          <ol className="mt-4 grid gap-3 text-[0.9375rem]">
            {[["Connect", "Pick the repositories on GitHub."], ["Read", "Trace reads one commit you choose and keeps short excerpts."], ["Learn", "You get questions and answers tied to exact files, lines and commits."]].map(([title, body], index) => (
              <li key={title} className="flex gap-3"><span aria-hidden="true" className="font-mono text-[0.75rem] text-primary-ink">0{index + 1}</span><span><strong className="font-semibold">{title}.</strong> <span className="text-secondary">{body}</span></span></li>
            ))}
          </ol>
        </section>
      </Enter>
    </div>
  );
}
