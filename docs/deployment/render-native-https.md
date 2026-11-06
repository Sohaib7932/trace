# Render-native HTTPS and CORS repair

## Root cause

Render terminates public TLS, redirects public HTTP to HTTPS and sends internal
HTTP to the application. Uvicorn's stock proxy middleware uses the same peer
allowlist for both original scheme and client IP. Trace's seven specific proxy
entries omit a private peer observed during the earlier mixed-result probe.
Unlisted hops leave the ASGI scheme as HTTP, and the HTTPS guard rejects the
request before ordinary CORS. Exact request-to-socket correlation was not
established, so individual failures are not attributed to a particular peer.
This produces intermittent `400 https_required` without ACAO rather than a
Supabase, database or frontend-origin failure.

A read-only 6 November 2026 probe made 60 consecutive fresh OPTIONS connections,
30 each to account/me and custom-lessons: 35 returned 200 with correct CORS and
25 returned `400 https_required`. Among the additional health/account/header
checks, every HTTPS failure had that same error code. Five plaintext requests
with spoofed forwarding headers all returned same-host HTTPS redirects; none
reached an application response. Twelve additional TLS account requests with a
caller-supplied `X-Forwarded-Proto: http` returned eight legitimate 401 responses
and four existing transport rejections. These are observations of the old
deployment, not post-fix production acceptance.

## Trust basis and its limits

[Render's public transport contract](https://render.com/docs/web-services#connecting-from-the-public-internet)
provides edge HTTPS enforcement and a primary port not directly public.
[Its tutorial](https://render.com/tutorials/web-service-vs-static-site/web-services)
instructs applications to use X-Forwarded-Proto for original scheme.
[Cloudflare documents](https://developers.cloudflare.com/fundamentals/reference/http-headers/#x-forwarded-proto)
that it overwrites caller-supplied protocol values. Public tests support this
behavior; they do not reveal every internal header transformation or constitute
cryptographic proof of a particular request's origin.

**Private traffic is a separate trust boundary.** Paid Render services can accept
requests to the same port from services in the same workspace and region.
Private callers can forge forwarding headers. Hostnames, Render process variables,
Cloudflare header names and canonical syntax do not authenticate such callers.
[Render private networking](https://render.com/docs/private-network) documents
this access; [environment isolation](https://render.com/docs/projects#blocking-cross-environment-traffic)
can limit cross-environment traffic but still permits same-environment peers.

The read-only workspace inventory at this checkpoint contains only trace-backend
in Frankfurt; five other web services are suspended in Oregon. This supports the
current narrow deployment perimeter, but is not a permanent firewall guarantee.
An operator must review and explicitly accept all private callers before enabling
this profile. Adding another same-region workload requires a new trust review.
Do not activate if untrusted private clients can reach the port. If private
requests themselves must be authenticated, an additional authenticated ingress
or enforceable network isolation is required. This patch does not pretend that
an XFP header supplies that authentication.

## Implementation

The optional Render profile accepts only one exact pinned Host and one exact
`X-Forwarded-Proto: https`. Missing, duplicate, chained or conflicting protocol
values fail closed, even if Uvicorn already set an HTTPS scheme. Forwarded,
X-Forwarded-For and arbitrary Cloudflare/client-IP headers cannot establish the
scheme. The profile changes only ASGI scheme; client-IP parsing keeps the stock
Uvicorn algorithm and unchanged seven-entry allowlist.

The launcher captures the actual socket before that stock parser. The existing
loopback health exception can therefore use genuine socket metadata, rather than
a rewritten client address. No public health bypass is introduced. TCP health
checks stay configured. Bare local GET/HEAD health is narrowly scoped and never
creates a learner identity.

An outer allowed-origin error-CORS envelope adds CORS headers to security errors
without handling OPTIONS or bypassing the HTTPS guard. Successful preflight
still requires both the transport policy and existing CORS policy to accept it.
Supabase authentication, ownership, origin validation, secure cookies, durable
admission, deterministic runtimes and provider budgets remain in place.

The default is disabled; other production deployments retain strict ASGI scheme
checks, and local development behavior remains unchanged. No frontend change,
Vercel access, SDK, database migration or
new public endpoint is needed. The prior OIDC work remains separately preserved
on the local `codex/vercel-oidc-production-gateway` branch/worktree and is not a
dependency of this repair.

## Exact rollout steps (not executed)

1. Review this PR, its test results and the private-network trust scope above.
   Keep PR #41 closed. Do not deploy from the OIDC branch.
2. Keep the existing frontend URL, all Vercel variables, Render database/auth/AI
   variables, PORT=8000, TCP health check and `TRACE_TRUSTED_PROXY_IPS` unchanged.
3. Verify Render supplies its documented process variables: `RENDER=true`,
   `RENDER_SERVICE_TYPE=web`, `RENDER_SERVICE_ID` and
   `RENDER_EXTERNAL_HOSTNAME=trace-backend-1lio.onrender.com`. These are public
   deployment metadata, not secrets and not request authentication.
4. After explicit approval of the reviewed code and private perimeter, set only:

   ```dotenv
   TRACE_RENDER_EDGE_MODE=enabled
   TRACE_RENDER_EDGE_HOSTNAME=trace-backend-1lio.onrender.com
   TRACE_RENDER_EDGE_TRUSTED_PRIVATE_PERIMETER_CONFIRMED=true
   ```

   The acknowledgment records an operator decision; setting it does not create
   network isolation. Never use it to conceal an unverified private path.
5. Deploy the reviewed backend commit through the existing root Dockerfile and
   production launcher. Do not rerun migrations. Confirm startup/readiness and
   the expected revision. Invalid or incomplete profile metadata must fail startup.
6. Repeat at least 30 consecutive real preflights per frontend route, public
   health/account/custom-lessons checks and spoofed-header tests. Investigate any
   `https_required`; do not replace failure evidence with a later successful retry.
   With no learner token, account/custom-lessons must return 401 with allowed
   CORS, not 200. Disallowed Origins must receive no ACAO.
7. Privately sign in through the unchanged Vercel frontend. Verify account data,
   owned lessons, ownership isolation, guest claiming and Notes verification.
   Only then continue the authorized protected-admin corpus import/publication
   and bounded real Gemini/lesson checks. Those are separate acceptance gates;
   transport tests or a healthy endpoint do not prove AI works.

Before approval, production remains unchanged and its existing intermittent
failures remain unresolved in the running revision. Roll back code and profile
as a matched pair; never change proxy trust, clear data or reset allowances.
