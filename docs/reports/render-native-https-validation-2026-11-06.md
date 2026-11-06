# Render-native HTTPS validation — 6 November 2026

Status: implemented and locally validated; production activation is not performed.
Base: `origin/main` at `f45428a2aa272e864001e92db624af8763f786da`.
Branch: `codex/render-native-https-repair`.

## Implementation and scope

The optional Render scheme policy is separate from the unchanged trusted-proxy
client-IP parser. It requires explicit deployment metadata, exact Host and
singleton HTTPS protocol plus an operator-confirmed private perimeter. An outer
error-CORS envelope does not short-circuit the HTTPS guard. The launcher captures
actual sockets before stock Uvicorn proxy handling to preserve genuine local
health behavior. Transport rejection logs contain fixed categories only.

Paths created:

- `backend/app/core/cors_errors.py`
- `backend/app/core/render_edge_middleware.py`
- `backend/app/core/render_edge_settings.py`
- `backend/tests/unit/test_render_edge_middleware.py`
- `backend/tests/unit/test_render_edge_settings.py`
- `backend/tests/integration/test_render_edge_http.py`
- `docs/deployment/render-native-https.md`
- This report.

Paths modified:

- `backend/app/main.py`
- `backend/scripts/run_production.py`
- `deploy/production.env.example` — disabled defaults/placeholders only.
- The canonical `.claude-logs/2026-10-31_10-25-36_01a18c8a-4fc7-70a0-bf35-3113cfa88f29.md`
  — the already reviewed, privacy-sanitized checkpoint from `60da24d`; genuine
  Codex attribution, 159 anchored prompts and 117 final-answer entries. The
  original checkpoint is separately preserved. This is a bounded historical
  checkpoint, not a claim that future answers or every delegated report were
  captured automatically.

Frontend source, package manifests, Vercel settings, migrations, the existing
HTTPS/request-limit middleware files and OpenAPI exports are unchanged. The
separate OIDC implementation remains in its original local worktree and is not
included. PR #41 was confirmed CLOSED with `mergedAt=null`.

## Executed validation

| Gate | Result |
| --- | --- |
| Final new Render settings/middleware and actual HTTP integration tests | PASS: 101 tests, 29.42 seconds |
| Relevant existing backend regressions | PASS: 343 tests, 384.52 seconds |
| Existing repository/logging script tests | PASS: 177 tests, 11.683 seconds |
| Full backend Ruff | PASS |
| Full backend formatting check | PASS: 436 Python files |
| Full strict mypy | PASS: 266 source files |
| Actual in-memory OpenAPI comparison | PASS: exact equality, 54 paths / 60 operations |
| Whitespace and protected-path diff checks | PASS |
| Credential-pattern scan of intentional changes | No credential found; only the existing production-template placeholder URL matched |

The final focused command was:

```text
python -B -m pytest tests/unit/test_render_edge_settings.py tests/unit/test_render_edge_middleware.py tests/integration/test_render_edge_http.py --no-cov --disable-socket --basetemp <unique-private-test-directory> -q
```

The 343-test regression run covered settings, JWT/JWKS, existing HTTPS/platform
contracts, accounts, learning and failures, legacy contracts, Phase 0 verification,
transfer/retrieval, custom lessons and concurrency, conversation tutor, live-AI
HTTP with controlled transports, feedback security, AI lifecycle, startup cleanup,
knowledge administration and versioned support HTTP.

The integration tests executed 36 consecutive preflights over account/me and
custom-lessons routes across nine route/peer combinations. They also verified
401 authentication, ownership 404, secure guest claiming, genuine Notes failed
and passing verification, idempotent readback and disposable database integrity.
They model Render normalization explicitly and are not real production evidence.

Tests used existing disposable database fixtures and blocked external sockets.
No production migrations, real AI calls, original development database writes or
backup modifications occurred. Full backend pytest and coverage were not rerun
for this Render repair; no full-suite/coverage baseline claim is made. The
obsolete OIDC full-suite run was interrupted after the strategy changed.
Frontend tests/build were not rerun because this branch has no frontend change.

Initial restricted static-check attempts could not write the new worktree caches;
the checks were rerun with access to those caches and passed. No lint rule,
assertion, test selection policy or coverage threshold was weakened.

## Live read-only observations of the old deployment

Sixty consecutive fresh-connection OPTIONS calls, 30 per browser route, produced
35 correct CORS successes and 25 `400 https_required` responses. Among the full
79-request probe, all 33 HTTP 400s had that guard code. Health/live returned 200,
health/ready and account/me returned that transport error, and custom-lessons
correctly returned unauthenticated 401. This is intermittent, not healthy.

Five plaintext spoof attempts all returned same-host HTTPS 301 redirects and no
application response. Additional TLS tests with single, chained and duplicate
caller-supplied protocol headers produced ordinary 401 responses on accepted
paths. Twelve extra TLS account requests supplying `X-Forwarded-Proto: http`
returned eight 401s and four existing guard failures. Public behavior supports
edge normalization, but does not identify every internal hop or authenticate a
private caller. Each observed `https_required` remains a failure of the current
unmodified deployment, not a post-fix success.

## Release gates

**PASS for a draft PR; not a production acceptance pass.** The paid service's
private port is reachable from same-workspace/region services. Current read-only
inventory shows only Trace in Frankfurt and five suspended web services in
Oregon. That inventory does not permanently enforce isolation. A private caller
inside the acknowledged perimeter can supply a matching Host/XFP; the profile
does not cryptographically authenticate that caller. Do not activate if any such
caller is untrusted. Default strict production mode continues rejecting raw
forwarded-header spoofing.

No production environment, compute plan, frontend domain, proxy allowlist, TCP
health configuration, database, provider allowance or deployment changed.
Actual post-fix production preflights, authenticated UI acceptance, protected
corpus import/publication and live Gemini lesson/support checks remain pending
the reviewed rollout. They must not be reported as passing from local tests.

Follow [the exact deployment and rollback steps](../deployment/render-native-https.md).
