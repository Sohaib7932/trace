import { NextResponse, type NextRequest } from "next/server";
import { serverAuth } from "@/lib/supabase/server";
import { authConfig } from "@/lib/supabase/config";
import { DEFAULT_NEXT, NEXT_COOKIE, safeNext } from "@/lib/auth/next-path";

export async function GET(request: NextRequest) {
  const params = request.nextUrl.searchParams;
  const supabase = await serverAuth(true);
  const recovery = params.get("type") === "recovery";
  let success = false;
  if (supabase && !params.has("error")) {
    const code = params.get("code");
    const tokenHash = params.get("token_hash");
    const type = params.get("type");
    try {
      if (code && code.length <= 2048) {
        const { error } = await supabase.auth.exchangeCodeForSession(code);
        success = !error;
      } else if (tokenHash && tokenHash.length <= 2048 && (type === "signup" || type === "recovery")) {
        // Confirmation/recovery links only. This never enables passwordless login.
        const { error } = await supabase.auth.verifyOtp({ token_hash: tokenHash, type });
        success = !error;
      }
    } catch { success = false; }
  }
  // Never trust query next, forwarded-host or provider error descriptions. The only
  // destination input is our own short-lived cookie, checked against a strict allowlist.
  const signupConfirmation = params.get("type") === "signup";
  const remembered = safeNext(decodeURIComponent(request.cookies.get(NEXT_COOKIE)?.value ?? ""));
  const destination = success
    ? recovery ? "/reset-password" : signupConfirmation ? "/account" : remembered ?? DEFAULT_NEXT
    : `/sign-in?auth_error=${failureKind(params)}`;
  // Next can normalize loopback hosts internally. Pin redirects to the configured app origin.
  const site = authConfig()?.siteUrl;
  if (!site) return new NextResponse("Account authentication is not configured.", { status: 503, headers: { "Cache-Control": "no-store" } });
  const response = NextResponse.redirect(new URL(destination, site), 303);
  response.headers.set("Cache-Control", "private, no-store");
  response.headers.set("Pragma", "no-cache");
  response.headers.set("Expires", "0");
  response.headers.set("Referrer-Policy", "no-referrer");
  response.cookies.set(NEXT_COOKIE, "", { path: "/auth", maxAge: 0 });
  return response;
}

/** Maps provider error codes to a fixed message key; provider text is never shown. */
function failureKind(params: URLSearchParams): "link" | "cancelled" | "provider" {
  const error = params.get("error") ?? "";
  const code = params.get("error_code") ?? "";
  const description = (params.get("error_description") ?? "").toLowerCase();
  if (error === "access_denied" && !description.includes("not enabled")) return "cancelled";
  if (code === "provider_disabled" || description.includes("provider is not enabled") || description.includes("unsupported provider")) return "provider";
  return "link";
}
