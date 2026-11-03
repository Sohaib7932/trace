"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { clearGitHubAuthorization, githubAuthorizationUrl, githubProjectsApi, pendingGitHubAuthorization, saveGitHubAuthorization } from "@/lib/api/github-projects";

export function GitHubProjectCallback() {
  const started = useRef(false);
  const [message, setMessage] = useState("Checking GitHub authorization…");
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const query = new URLSearchParams(window.location.search);
    // Do not retain the one-time code in the address bar or navigation history.
    window.history.replaceState(null, "", "/projects/github/callback");
    void (async () => {
      try {
        if (query.has("error")) throw new Error("GitHub authorization was not completed.");
        const state = query.get("state") ?? "";
        const pending = pendingGitHubAuthorization(state);
        const code = query.get("code");
        if (!code) {
          const installation = query.get("installation_id") ?? "";
          if (!/^[1-9][0-9]{0,14}$/.test(installation)) throw new Error("No selected installation was returned. Start again.");
          saveGitHubAuthorization({ ...pending, installation_id: Number(installation) });
          window.location.assign(githubAuthorizationUrl(pending.authorization_url, "authorize"));
          return;
        }
        if (!pending.installation_id) throw new Error("The installation step is missing. Start again.");
        await githubProjectsApi.complete({ installation_id: pending.installation_id, state, code });
        clearGitHubAuthorization();
        window.location.replace("/projects");
      } catch {
        clearGitHubAuthorization();
        setMessage("GitHub connection could not be completed. Sign in with the same Trace account and start again. The app owner may still need to configure GitHub.");
      }
    })();
  }, []);
  return <section className="py-12"><h1 className="type-h3">GitHub connection</h1><p role="status" className="mt-4">{message}</p><Link href="/projects" className="mt-6 inline-block underline">Return to Project Learning</Link></section>;
}
