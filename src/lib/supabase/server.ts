import "server-only";
import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";
import { connection } from "next/server";
import { authConfig, authCookieOptions } from "./config";

export async function serverAuth(writable = false) {
  const config = authConfig();
  if (!config) return null;
  // SDK auth listeners read the clock before their lazy cookie access. Keep those
  // reads out of Next's partial prerender, including background route prefetches.
  if (!writable) await connection();
  const jar = await cookies();
  return createServerClient(config.url, config.key, {
    cookieOptions: authCookieOptions(config.siteUrl),
    cookies: {
      getAll: () => jar.getAll(),
      // Rendering only reads; proxy refreshes. Route handlers explicitly enable writes.
      ...(writable ? { setAll(values: { name: string; value: string; options: import("@supabase/ssr").CookieOptions }[]) {
        values.forEach(({ name, value, options }) => jar.set(name, value, options));
      } } : {}),
    },
  });
}
