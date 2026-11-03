# GitHub sign-in setup and acceptance

GitHub sign-in uses the existing Supabase Auth client, PKCE callback, session
cookies, safe redirect allowlist and backend JWT verification. It does not grant
Trace repository, commit or GitHub App access. Do not add repository scopes.

## External setup by the project owner

1. Open the shared Supabase project's Authentication → Sign In / Providers →
   GitHub. Copy the exact OAuth callback URL displayed there. It belongs to
   Supabase Auth, not the Next.js `/auth/callback` route.
2. In GitHub Settings → Developer settings → OAuth Apps, register an OAuth App.
   Use the intended Trace site as Homepage URL and the exact Supabase-displayed
   URL as Authorization callback URL. Check the correct project/environment.
3. Configure the OAuth App's Client ID and Client Secret privately in that
   Supabase GitHub provider configuration; enable and save the provider. These
   values do not belong in `.env.local`, source code, Git or chat logs.
4. In Supabase Auth URL configuration, set the intended Site URL and allow the
   exact application callback (`http://localhost:3000/auth/callback` locally).
   Add a separately reviewed HTTPS callback for each deployed environment; avoid
   unrestricted wildcard redirects.
5. Configure Trace's existing public Supabase URL/publishable key and site URL
   in the root `.env.local`; use the same project's issuer/JWKS in `backend/.env`.
   No additional backend GitHub credential is required. Restart/rebuild Next
   after changing its public configuration.
6. Sign in privately through **Continue with GitHub**. Inspect the provider's
   permission screen. Stop if it unexpectedly requests repository permissions.
   Return through Supabase and Trace's existing PKCE code exchange.

The hosted provider settings returned `github: false`, `google: true` during the
3 November 2026 initial audit. This is a point-in-time observation, not a claim
that later dashboard configuration has been performed.

## Account ownership

Supabase owns verified-email identity linking. Trace continues to key accounts
by the verified issuer and subject, with a database uniqueness constraint.
It does not create a second profile merely because the provider is GitHub and
does not merge accounts by trusting a client-supplied email. Use the same
verified identity to test provider linking; differing identities may represent
different accounts. Do not silently reassign learner history between them.

## Manual acceptance

- Test both sign-in and sign-up entry points and the configured-origin check.
- Cancel at GitHub; expect a fixed safe cancellation message, no raw OAuth error.
- Disable the provider in a disposable project only; expect a clear setup error.
- After successful login, check account access and an owned learner session.
- Reload, navigate between protected pages, and test token refresh/persistence.
- Sign out; protected access must disappear. Test another controlled account to
  confirm foreign sessions remain inaccessible.
- Test an attempted external `next` redirect; only the existing safe remembered
  destination is allowed. Do not copy callback codes or tokens into evidence.
- Confirm email/password and Google sign-in still work separately.

Component/callback tests use controlled fixtures and cannot establish real
GitHub dashboard readiness. Mark live OAuth verified only after the genuine
external browser round trip succeeds.

Sources: [Supabase GitHub sign-in](https://supabase.com/docs/guides/auth/social-sign-in/auth-github),
[Supabase identity linking](https://supabase.com/docs/guides/auth/auth-identity-linking).
