# Authenticated production ingress

The existing production Vercel URL serves the same-origin `/api/v1` relay. The
relay forwards a Vercel Function workload credential to the fixed Render
origin. Render checks the workload against Vercel's official keys and the
pinned production identity. Supabase learner authorization remains separate.
Trace accepts the HTTPS scheme from a verified workload and keeps its current
socket and client-IP policy. This uses the existing Git integration, Function,
Render service and database.

## Prove the production identity

1. Review the source and require passing checks. Merge the reviewed PR into
   the existing Git-linked production branch. Verify that Vercel reports the
   expected production deployment.
2. Send a credential-free `GET /api/trace-ingress/identity` to the existing
   frontend HTTPS URL. The route reports only a verified identity fingerprint,
   issuer and Git commit. Confirm the commit equals the reviewed deployment.
   An unavailable response means the managed production identity has not been
   established. The Vercel project must already provide its OIDC runtime token
   for this owner-access-free release to proceed.
3. Save the verified public fingerprint as `TRACE_INGRESS_IDENTITY_SHA256` in
   Render. Choose `TRACE_INGRESS_ISSUER_MODE=team` for the pinned team issuer or
   `global` for the official global issuer. Set `TRACE_INGRESS_MODE=verify`
   and keep `TRACE_RENDER_EDGE_MODE=disabled`. Deploy the reviewed commit to the
   existing Render service. Verify mode accepts a valid workload credential;
   requests without one still use the existing transport rules during this stage.
4. Run `python -B -m scripts.check_deployed_transport --gateway-probe verify`
   from the backend checkout. The check sends 30 credential-free requests per
   protected route through Vercel. Each must reach the learner authentication
   check and carry Render's workload-verification marker. The direct forged
   credential must be rejected. The existing `0015` readiness response may still
   be `503` in this stage. Retain the results from every request.

## Cut over after the HTTPS proof

1. Use the approved write pause, verify active jobs and other writers have
   drained, and take a fresh encrypted backup with a successful isolated
   restore. Confirm the production `trace` schema and its exact starting head
   `0015_project_learning_paths`.
2. Apply only `0016_guard_search_paths` from the pinned release. Verify the
   new head and the seven function search paths against the saved state.
3. Set `TRACE_INGRESS_MODE=required` and deploy the reviewed commit through the
   same Render service. Keep the write pause until local readiness and the
   deployed commit are verified. Required mode rejects direct application calls
   without valid workload identity. The TCP health check is independent of
   workload authorization.
4. Reopen traffic and run `python -B -m scripts.check_deployed_transport
   --gateway-probe required` as one command. It requires public relay readiness
   `200` and rejection of direct application requests and preflights without
   workload proof. Browser requests to the same-origin relay do not need
   cross-origin preflight.
5. Verify signed-in access, guest-cookie claiming and existing lesson flows.
   To run the protected corpus and lesson operators through the fixed frontend
   relay, set process-only `TRACE_OPERATOR_USE_GATEWAY=1` and provide the existing
   approved operator credentials privately. The normal administrator or learner
   authorization still applies. Follow the bounded live feature acceptance in
   [the production integration runbook](production-integration.md).

[Vercel OIDC system variable](https://vercel.com/docs/environment-variables/system-environment-variables#vercel_oidc_token)
describes when the production Function receives its credential. The probe uses
the [official Vercel OIDC claim format](https://vercel.com/docs/oidc/reference#oidc-token-anatomy).
