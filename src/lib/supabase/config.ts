export function authConfig() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;
  const siteUrl = process.env.NEXT_PUBLIC_SITE_URL;
  if (!url || !key || !siteUrl) return null;
  try {
    const parsed = new URL(url);
    const site = new URL(siteUrl);
    if (parsed.username || parsed.password || parsed.search || parsed.hash || parsed.pathname !== "/" ||
      !(parsed.protocol === "https:" || parsed.protocol === "http:" && ["localhost", "127.0.0.1", "[::1]"].includes(parsed.hostname)) ||
      !key.startsWith("sb_publishable_")) return null;
    if (site.username || site.password || site.search || site.hash || site.pathname !== "/" ||
      !(site.protocol === "https:" || site.protocol === "http:" && ["localhost", "127.0.0.1", "[::1]"].includes(site.hostname))) return null;
    return { url: parsed.origin, key, siteUrl: site.origin };
  } catch { return null; }
}

export function authCookieOptions(url: string) {
  // The official browser SDK needs readable cookies to refresh and send Bearer tokens.
  return { path: "/", sameSite: "lax" as const, secure: url.startsWith("https:"), httpOnly: false };
}
