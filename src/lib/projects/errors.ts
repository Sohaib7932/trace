import { ApiError } from "@/lib/api/client";

/** What the page shows for a failed Project Learning call. Messages are ours; only the request id comes from the server. */
export type ProjectErrorInfo = {
  title: string;
  detail: string;
  /** One clear next step. `retry` means "run the same action again". */
  action?: { label: string; href?: string; retry?: boolean };
  requestId: string | null;
  /** The server's error code, shown only under Support details. */
  code?: string | null;
  /** The feature isn't switched on for this server (not a user mistake). */
  unavailable?: boolean;
};

const signIn = { label: "Sign in again", href: "/sign-in?next=%2Fprojects" } as const;
const reconnect = { label: "Connect GitHub again", href: "/projects/connect" } as const;

/**
 * Maps the backend's error codes to specific messages. The backend signals "feature off" as a 503 with
 * `dependency_unavailable` (the GitHub App mode is disabled) or `github_not_configured`.
 */
export function describeProjectError(error: unknown): ProjectErrorInfo {
  if (!(error instanceof ApiError)) {
    return { title: "Something went wrong", detail: "Nothing was changed that we know of. Try again.", action: { label: "Try again", retry: true }, requestId: null };
  }
  const requestId = error.requestId;
  const code = error.code ?? "";
  const make = (title: string, detail: string, action?: ProjectErrorInfo["action"], unavailable = false): ProjectErrorInfo => ({ title, detail, action, requestId, unavailable, code: error.code });

  if (error.status === 0) {
    return make(
      error.code === "request_cancelled" ? "Request stopped" : "Trace couldn't reach the server",
      error.code === "client_timeout"
        ? "The server didn't answer in time, so we can't tell whether the last step finished. Check the current state before you repeat it."
        : "Check that the Trace backend is running and that this page and the backend both use the same address (localhost, not 127.0.0.1).",
      { label: "Try again", retry: true },
    );
  }
  if (error.status === 401 || code === "unauthenticated") return make("Sign in again", "Your sign-in needs renewing before Trace can use your GitHub connection.", signIn);
  switch (code) {
    case "github_not_configured":
      return make("GitHub import isn't enabled on this server yet", "The person who runs this Trace server has to turn on the GitHub App first. Nothing is wrong with your account.", undefined, true);
    case "dependency_unavailable":
      return make("Project Learning isn't ready on this server", "The server reported that something it depends on isn't ready (for example its database needs the latest update, or the GitHub App settings aren't loaded). Nothing is wrong with your account. Whoever runs the server can check the request ID below.", { label: "Try again", retry: true });
    case "github_unavailable":
      return make("GitHub isn't answering right now", "Trace couldn't reach GitHub. Wait a moment and try again.", { label: "Try again", retry: true });
    case "github_timeout":
    case "github_deadline":
    case "github_request_deadline":
      return make("GitHub took too long", "The last step may or may not have finished. Check the current state, then repeat it if needed.", { label: "Try again", retry: true });
    case "github_state_invalid":
      return make("This connection attempt expired", "Each GitHub connection link works once and only for a few minutes. Start a fresh one.", reconnect);
    case "github_installation_missing":
      return make("The GitHub App isn't installed for that account", "Install the Trace GitHub App on the GitHub account that owns your repositories, choosing only the ones you want.", reconnect);
    case "github_installation_selection_required":
      return make("More than one installation was found", "Trace couldn't pick one for you. Reconnect and choose the installation you want to use.", reconnect);
    case "github_installation_inaccessible":
      return make("GitHub denied access to that installation", "Use the same GitHub account that installed the App, or ask its owner to add you.", reconnect);
    case "github_reauthorization_required":
    case "github_access_changed":
      return make("Your GitHub access changed on GitHub", "The installation or its repositories were changed or removed. Connect again to refresh what Trace may read.", reconnect);
    case "github_permissions":
      return make("The App needs read-only access to selected repositories", "Change the installation on GitHub to selected repositories with read-only permissions, then connect again.", reconnect);
    case "github_file_omitted":
      return make("That file is too large or unsupported", "Trace skips very large files, binaries and secrets. Choose a smaller project or a different commit.");
    case "github_no_safe_sources":
      return make("No safe source files were found", "Everything in this commit was skipped (secrets, binaries, very large or generated files). Pick a commit that has regular source code.");
    case "github_limit":
      return make("Too many repositories", "Trace can list at most 100 repositories from one installation. Reduce the repositories the App can see on GitHub.");
    case "github_rate_limited":
    case "rate_limited":
      return make("You're going a little fast", "Trace or GitHub is limiting requests. Wait about a minute, then try again.", { label: "Try again", retry: true });
    case "quota":
    case "quota_exhausted":
      return make("The AI allowance is used up for now", "Trace can't generate more project lessons or answers right now. Try again later; nothing you saved was lost.");
    default:
  }
  if (error.status === 404) return make("Not found", "This item isn't available to your account.");
  if (error.status === 409) return make("That changed on the server", "Refresh and try again.", { label: "Try again", retry: true });
  if (error.status === 429) return make("You're going a little fast", "Wait about a minute, then try again.", { label: "Try again", retry: true });
  if (error.status === 504) return make("The server took too long", "The last step may or may not have finished. Check the current state before repeating it.", { label: "Try again", retry: true });
  if (error.status >= 500) return make("The server had a problem", "This isn't caused by anything you did. Try again in a moment.", { label: "Try again", retry: true });
  return make("That didn't work", "Try again.", { label: "Try again", retry: true });
}

/** True for the "feature is off" signal, so pages can show one calm unavailable state. */
export function isProjectsUnavailable(error: unknown): boolean {
  return describeProjectError(error).unavailable === true;
}
