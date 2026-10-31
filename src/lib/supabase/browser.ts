"use client";

import { createBrowserClient } from "@supabase/ssr";
import { authConfig, authCookieOptions } from "./config";

export function browserAuth() {
  const config = authConfig();
  if (!config) return null;
  return createBrowserClient(config.url, config.key, {
    cookieOptions: authCookieOptions(config.siteUrl),
    auth: { flowType: "pkce" },
  });
}
