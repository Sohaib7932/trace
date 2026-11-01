/**
 * Post-sign-in destinations. Only a small allowlist of same-origin app paths is ever
 * accepted, so a crafted ?next= can't send someone to another site or an auth loop.
 */
const ALLOWED = /^\/(?:learn(?:\/[a-z0-9-]{1,80})?|account)?(?:#[a-z0-9-]{1,40})?$/;

export const DEFAULT_NEXT = "/learn";
export const NEXT_COOKIE = "trace_next";

export function safeNext(value: string | null | undefined): string | null {
  if (!value || value.length > 160) return null;
  return ALLOWED.test(value) ? value : null;
}

/** Remembers the destination for the OAuth round trip (10 minutes, this site only). */
export function rememberNext(value: string | null) {
  const next = safeNext(value);
  if (!next) return;
  document.cookie = `${NEXT_COOKIE}=${encodeURIComponent(next)}; Path=/auth; Max-Age=600; SameSite=Lax${location.protocol === "https:" ? "; Secure" : ""}`;
}
