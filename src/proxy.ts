import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";
import { authConfig, authCookieOptions } from "@/lib/supabase/config";

export async function proxy(request: NextRequest) {
  let response = NextResponse.next({ request });
  const config = authConfig();
  if (config) {
    const supabase = createServerClient(config.url, config.key, {
      cookieOptions: authCookieOptions(config.siteUrl),
      cookies: {
        getAll: () => request.cookies.getAll(),
        setAll(values, headers) {
          values.forEach(({ name, value }) => request.cookies.set(name, value));
          const previous = response.cookies.getAll();
          response = NextResponse.next({ request });
          previous.forEach((cookie) => response.cookies.set(cookie));
          values.forEach(({ name, value, options }) => response.cookies.set(name, value, options));
          Object.entries(headers).forEach(([key, value]) => response.headers.set(key, value));
        },
      },
    });
    // Verification also performs the SDK's documented refresh. Never authorize getSession().user.
    await supabase.auth.getClaims().catch(() => null);
  }
  response.headers.set("Cache-Control", "private, no-store");
  response.headers.set("Pragma", "no-cache");
  response.headers.set("Expires", "0");
  response.headers.set("Referrer-Policy", "no-referrer");
  return response;
}

export const config = {
  matcher: ["/account/:path*", "/auth/:path*", "/sign-in", "/sign-up", "/forgot-password", "/reset-password", "/learn/:path*"],
};
