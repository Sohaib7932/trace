# Projects (GitHub): manual test checklist

Run this in a browser with the backend started **by you**, in a terminal where the GitHub App variables are
loaded. The frontend never reads those values. Variable **names** only: `TRACE_GITHUB_APP_MODE` (`disabled` or
`enabled`), `TRACE_GITHUB_APP_ID`, `TRACE_GITHUB_APP_SLUG`, `TRACE_GITHUB_APP_CLIENT_ID`,
`TRACE_GITHUB_APP_CLIENT_SECRET`, `TRACE_GITHUB_APP_PRIVATE_KEY`, `TRACE_GITHUB_APP_STATE_SIGNING_SECRET`,
`TRACE_GITHUB_APP_TOKEN_ENCRYPTION_KEY`, `TRACE_GITHUB_APP_CALLBACK_URL`.

Use **`http://localhost:3000`** for the site and **`http://localhost:8000`** for the API. Do not mix `localhost`
and `127.0.0.1`: cookies, the GitHub callback address and CORS all depend on one hostname.

On the GitHub App settings page, the callback URL must be exactly `http://localhost:3000/projects/github/callback`,
repository permissions must be read-only, and "Request user authorization (OAuth) during installation" should be on.

## Steps

| # | Do this | You should see |
|---|---|---|
| 1 | Start the backend with the GitHub variables loaded, then the site (`npm run dev`). Open `/projects` while signed out. | One "Sign in to use Projects" card. No network call to `/api/v1/projects/*` (check DevTools). |
| 2 | Sign in, open `/projects`. | If `TRACE_GITHUB_APP_MODE` is `enabled`: a "Connect GitHub" hero with the animated trace line. If it is `disabled`: "GitHub import isn't enabled on this server yet" and no buttons. |
| 3 | Open `/projects/connect`. | A consent card (what is read, what goes to the AI, what is never read, how to leave). "Continue to GitHub" is disabled until the box is ticked. |
| 4 | Tick the box and press "Continue to GitHub". | The browser goes to `github.com` (only a `github.com` address is ever followed). |
| 5 | On GitHub, install the App on one **small** repository (or authorize the existing installation) and approve. | You return to `/projects/github/callback`, the address bar is cleaned straight away, progress shows, then "GitHub is connected" and you land on `/projects/import`. |
| 6 | On `/projects/import`, search for the repository, tick it. | An animated checkbox, the selection counter, and the "Add selected" bar (sticky on phones). Repositories you already added are marked and cannot be ticked again. |
| 7 | Press "Add selected". | A per-repository list (Waiting, Adding, Added). One repository sends you to its project page. |
| 8 | On the project page, copy the full commit SHA from GitHub (Commits, then copy the full 40-character ID) and paste it. | "Looks right." Press "Use this commit". The short SHA appears as a chip. |
| 9 | Press the orange button ("Fetch snapshot and continue"). | The progress tracker moves: Fetching, Indexing, Analyzing, each with a pulse while it runs. Then "What Trace read" with counts and a list of skipped kinds. |
| 10 | Open "Excerpts that can be used". | Each excerpt shows the file path, line range and short commit SHA. Long lines scroll inside the box. |
| 11 | Press "Open the learning path". | A title, a badge saying AI-generated (or Test fixture), "Practice only · ungraded · Not executed", numbered steps, each with a question and collapsible sources. |
| 12 | Open the project tutor (bottom bar) and ask a question about the code. | An answer labelled "AI explanation · Ungraded · Not executed" with citations (path, lines, commit, quote). Nothing is marked right or wrong. |
| 13 | Make a commit on GitHub, paste its new SHA on the project page, run the steps again. | New results for the new commit; the old commit's results are untouched. |
| 14 | Open Manage. Press "Disconnect this repository", confirm. | You return to `/projects` and the project is gone from the list. |
| 15 | Account, Settings. | A GitHub card showing connected or not, with a link to Projects. |
| 16 | Re-add a repository, open Manage, "Disconnect GitHub entirely", confirm. | The installation disappears; `/projects` shows the Connect hero again. "Delete stored project data" explains it is not available yet. |

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| "GitHub import isn't enabled on this server yet" | `TRACE_GITHUB_APP_MODE` is `disabled` or an owner value is missing (the backend answers `503`) | Start the backend with mode `enabled` and every `TRACE_GITHUB_APP_*` name set, then restart it. |
| GitHub says the redirect URI is not associated with the App | The App's callback URL differs from the one in `TRACE_GITHUB_APP_CALLBACK_URL` | Set both to exactly `http://localhost:3000/projects/github/callback` (path included, no query). |
| "This connection attempt expired" | The link is single use and short lived, or you used another browser or tab | Start again from `/projects/connect` in the same browser and finish within a few minutes. |
| "The GitHub App isn't installed for that account" (`github_installation_missing`) | The App is not installed where you authorized | Use the install path ("Change which repositories the App can see") and pick your repositories. |
| A repository is missing from the picker | The App was not given that repository | GitHub, Settings, Applications, the App, Configure, add the repository; then reload the picker. |
| "More than one installation was found" | You have several installations | Reconnect and choose the one you want. |
| "You're going a little fast" (`429`) | Per-account rate limit | Wait about a minute. Requests from this tab are already sent one at a time. |
| "The AI allowance is used up for now" | AI quota reached | Try later; nothing saved is lost. |
| "Trace couldn't reach the server" | Backend not running or stale (an older build without the GitHub paths) | Start it and check `http://localhost:8000/openapi.json` lists `/api/v1/projects/github/...`. |
| Everything signs you out or returns `401` | Site and API use different hostnames (`localhost` vs `127.0.0.1`) | Use `localhost` for both. |
| "Sign in to use Projects" after you signed in | The session did not reach this origin | Reload after signing in on the same hostname. |
| "GitHub access changed" | The installation or repository was changed on GitHub | Connect again from `/projects/connect`. |
