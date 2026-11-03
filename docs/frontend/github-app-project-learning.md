# GitHub App Project Learning

GitHub repository connection and optional Supabase GitHub social sign-in are
separate flows. This feature authenticates an already signed-in Trace learner,
proves their GitHub user access, and reads explicitly selected repositories.
It neither creates a Trace login nor grants an agent permission to modify GitHub.

Implementation is opt-in and disabled by default. No GitHub App has been
configured or live repository authorized by this implementation. Automated
tests use synthetic keys, tokens, HTTP responses, repositories and AI text.
Do not label those tests live GitHub or live Gemini verification.

## Owner configuration

The owner must register a **GitHub App**, not an OAuth App. Configure:

- Homepage: the intended Trace frontend origin.
- User authorization callback: exact frontend URL
  `http://localhost:3000/projects/github/callback` for local development; use an
  explicitly approved HTTPS origin for deployment.
- Setup URL after installation: the same exact frontend callback.
- Keep automatic user authorization during installation disabled: Trace's
  two-stage flow explicitly starts user authorization after the installation
  callback and preserves the owner-bound state. Do not add arbitrary redirects.
- Repository permissions: **Contents: Read-only**, **Pull requests: Read-only**,
  and mandatory **Metadata: Read-only**. No repository writes, administration,
  secrets, Actions, organization membership, email or other account permissions.
- Install using **Only select repositories**. The backend rejects all-repository
  installation selection, suspended installations, another App's installation,
  write grants or unexpected repository permission categories.
- This version performs read-time access revalidation and polling. No webhook
  endpoint exists; do not invent a webhook URL or expose a webhook secret.

Generate the App's RSA private key through GitHub and configure it privately on
the backend owner machine. The App ID and OAuth Client ID differ. The Client
Secret is used only for the server-side user OAuth exchange. Configure an
independent random state-signing secret of at least 32 characters.

The exact variable names are documented in
[`backend/github.env.example`](../../backend/github.env.example). The file is a
template, not an automatically loaded settings file. Configure private values in
the backend process environment or approved secret manager. The strict general
`backend/.env` rejects unknown GitHub settings, so do not append them there.
No GitHub private key, Client Secret, user token or installation token belongs
in root `.env.local`, frontend source, `NEXT_PUBLIC_*`, Git or chat.

For a local PowerShell process, set the public App ID, slug, Client ID and callback
variables privately; enter secrets with a masked prompt and load the private key
from its owner-controlled PEM file. Then explicitly set
`TRACE_GITHUB_APP_MODE=enabled` and start the backend with its ordinary approved
launcher. Do not paste secrets into command arguments or terminal transcripts.
No setting change here provisions cloud resources or authorizes paid AI usage.

## Connection sequence

1. The signed-in learner opens `/projects` and chooses Connect GitHub.
2. `POST /api/v1/projects/github/installations/start` returns the installation
   URL, user authorization URL, signed state and ten-minute expiry. URLs are
   fixed to GitHub; state is bound to the current Trace account and a durable
   single-use nonce.
3. The browser stores only pending flow metadata in session memory and visits
   GitHub installation selection. The owner reviews exact permissions and
   selected repositories. No installation is performed automatically by Codex.
4. GitHub returns `installation_id` and state to the setup callback. The frontend
   validates pending state and begins the returned GitHub user authorization URL.
5. GitHub returns a one-use `code` and state. The callback strips its query,
   submits the protected complete request and clears pending state.
6. `POST /installations/complete` exchanges the code server-side, identifies the
   authenticated GitHub user and calls the user-scoped installation repository
   API. An installation ID alone never grants access. The App's configuration
   and selected/read-only permissions are independently checked.
7. The learner lists live authorized repositories and explicitly connects one.
   Every read/ingestion rechecks both user access and App selection. Ingestion
   uses a fresh read-only installation token scoped to that single repository.

The callback requires the same signed-in Trace account that started the flow.
Replay, expiration, changed accounts, malformed state or failed code exchange
require restarting authorization. Failure never retains an unproven grant.

Tokens are not stored in the database or sent to the frontend. User proof stays
only in a bounded process-memory cache for at most five minutes. Restart, expiry
or routing to another worker requires reauthorization; this is an explicit
pilot limitation, not a durable distributed OAuth-session implementation.
Durable connections and snapshots survive it, but cannot be read/released until
current GitHub access is proved again. There is no silent App-only access after
the GitHub user's authorization is lost.

## HTTP contracts

All paths below start with `/api/v1/projects/github`. They require a signed-in
learner Bearer token, allowed Origin and `X-Trace-Client: learning-web`, and return
`Cache-Control: no-store`. Session cookies alone do not grant account access.

| Method/path | Input | Output |
| --- | --- | --- |
| POST `/installations/start` | No body | `installation_url`, `authorization_url`, `state`, `expires_at` |
| POST `/installations/complete` | `{installation_id,code,state}` | `{installation_id,repository_selection:"selected",authorization_expires_at}` |
| GET `/installations` | None | Array of the owned installation summaries above |
| GET `/installations/{installation_id}/repositories` | None | Array of `{repository_id,full_name,private}` currently authorized |
| POST `/repositories` | `{installation_id,repository_id}` | Owned connection `{id,installation_id,repository_id,full_name,private}` |
| GET `/repositories` | None | Array of owned connection summaries |
| POST `/repositories/{id}/sync` | `{commit_sha}` | Immutable pinned `ProjectSnapshot` |
| GET `/repositories/{id}/snapshot?commit_sha=...` | Exact commit SHA query | Same stored snapshot, after current access recheck |
| POST `/repositories/{id}/learning-path` | `{commit_sha}` | Ready/unavailable grounded ungraded learning path |

Commit SHA must be exactly forty lowercase hexadecimal characters, never a
branch, arbitrary URL or filesystem path. Connection creation is idempotent for
the owned repository/installation. Duplicate ingestion returns the original
stored receipt for that SHA. Changed installation/name needs an explicit new
authorization decision; no silent repository transfer occurs.

Missing account is 401, forbidden origin/role is 403, foreign/missing connection
is indistinguishable 404, replay or stale authorization is 409, malformed input
422, admission exhaustion 429, unavailable configuration/upstream dependency
503 and request deadline 504. Error details are sanitized. The middleware may
generalize the message; do not depend on private upstream error text. Project
operations admit ten calls per account/minute with one active call per account
and two globally, plus existing ingress limits. Do not poll in a retry loop.
No automatic OAuth POST or paid AI retry is implemented.

## Ingestion and grounding limits

Snapshots persist the selected repository connection, exact commit SHA,
canonical SHA-256 digest and bounded references. Commit title, up to twelve
changed files and up to five associated PR titles are inspected. Permitted code
files are read using the blob SHA supplied by that exact commit, at most 32 KiB
each; source excerpts are capped
at 1,000 characters. References include exact path and content digest.

Only approved extensions and safe relative source paths are fetched. Dotfiles,
environment files, credentials, private-key material, unsafe paths and binary
content are excluded. There is no clone, shell command, arbitrary HTTP/file
loader, code execution or repository write. The blob API reads symlink text
itself; it never follows a safe-looking filename
into an excluded environment file. Pagination is bounded; installations
over 100 accessible repositories fail explicitly. The result always states
`complete_repository:false`: this is changed-file learning, not a claim to have
indexed or understood an entire repository or every PR diff/history.

Oversized, unsupported-encoding or non-UTF-8 blobs are explicitly counted as
omitted files while other safe pinned references remain available. Upstream
authentication, network and integrity failures abort ingestion as unavailable;
they are never concealed as ordinary file omissions.

The only dotfile exception is the shared `.claude-logs/*.md` cohort directory.
The parser accepts counted native `PROMPT`/`RESPONSE` entries matching the actual
project logger format. Frontmatter, source paths in metadata, tools, reasoning,
unknown entry kinds, uncounted tails and oversized blocks are withheld. Obvious
credential and email patterns are rejected before storage/AI context. These
filters are defense in depth, not a guarantee that arbitrary repository text
contains no sensitive material. Connect only repositories approved for processing.
Logs remain untrusted claims, never evidence that code executed or a learner
achieved anything. Legacy/nonconforming agent log formats are omitted rather
than misrepresented as native capture.

The shared AI `generation` capability receives only the owned pinned safe source
bundle as untrusted data. It returns a bounded learning path with explanations
and questions, each citing existing reference IDs. Unknown citations, links,
private material and prohibited execution/completion/competency claims reject
the entire response. Citation membership is checked mechanically; it is not a
proof that every natural-language sentence is semantically correct. Suggested
paths are explicitly ungraded and unexecuted and cannot complete a lesson.
They do not create a lesson-spec evaluator, publish a candidate, assign a learner
exercise or change the deterministic Notes/Tasks verification system.

Snapshots and provenance are durable and immutable, including database update/
delete guards. Generated Project Learning path wording is currently a response,
not a persisted course/progress record. Broad-topic private learning guides use
their separate owner-scoped persistence; do not confuse these formats. All user
history and existing lesson data remain intact. Migration 0011 is additive after
0010; populated project-history downgrade refuses to erase records. No real local
or production database upgrade was performed by this implementation.

## Manual acceptance after owner setup

Use a small non-sensitive repository containing a controlled commit, PR and
native cohort prompt/final log. Sign in privately, install selected/read-only,
complete user authorization, select the repository, ingest the exact commit and
compare references against GitHub at that SHA. Generate a path and inspect every
citation. Confirm no secrets, raw tokens or unexpected files enter responses.
Repeat with another Trace account to verify isolation; then revoke user/App
access and confirm snapshot/path release fails. Test cancellation, tampered and
replayed callback state, expiration and restart/re-auth behavior. Verify genuine
Gemini output separately from deterministic fixtures. Do not mark live acceptance
until this real round trip has been observed.

Primary references: [GitHub App user authorization](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-user-access-token-for-a-github-app),
[GitHub App security practices](https://docs.github.com/en/apps/creating-github-apps/about-creating-github-apps/best-practices-for-creating-a-github-app),
[Apps versus OAuth apps](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/differences-between-github-apps-and-oauth-apps).
