import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { NextRequest } from "next/server";
import { authConfig, authCookieOptions } from "@/lib/supabase/config";
import { GET } from "@/app/auth/callback/route";
import { RequireAccount } from "@/components/auth/require-account";

const fixture = vi.hoisted(() => ({
  configured: true, claims: vi.fn(), exchange: vi.fn(), verify: vi.fn(), redirect: vi.fn(),
}));
vi.mock("@/lib/supabase/server", () => ({ serverAuth: async () => fixture.configured ? { auth: { getClaims: fixture.claims, exchangeCodeForSession: fixture.exchange, verifyOtp: fixture.verify } } : null }));
vi.mock("next/navigation", () => ({ redirect: (path: string) => { fixture.redirect(path); throw new Error("redirected"); } }));
afterEach(() => vi.unstubAllEnvs());
beforeEach(() => {
  vi.unstubAllEnvs(); vi.clearAllMocks(); fixture.configured = true;
  vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", "https://auth.example.test");
  vi.stubEnv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY", "sb_publishable_test_fixture");
  vi.stubEnv("NEXT_PUBLIC_SITE_URL", "https://trace.example.test");
  fixture.claims.mockResolvedValue({ data: { claims: { sub: "verified" } }, error: null });
  fixture.exchange.mockResolvedValue({ error: null }); fixture.verify.mockResolvedValue({ error: null });
});
test("only valid public configuration and app origins enable authentication", () => {
  expect(authConfig()?.siteUrl).toBe("https://trace.example.test");
  vi.stubEnv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY", "sb_secret_never_use_in_browser");
  expect(authConfig()).toBeNull();
  vi.stubEnv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY", "sb_publishable_test_fixture");
  vi.stubEnv("NEXT_PUBLIC_SITE_URL", "http://public.example.test"); expect(authConfig()).toBeNull();
  vi.stubEnv("NEXT_PUBLIC_SITE_URL", "http://127.0.0.1:3000"); expect(authConfig()).not.toBeNull();
  vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", "https://user:password@auth.example.test"); expect(authConfig()).toBeNull();
  vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", "invalid"); expect(authConfig()).toBeNull();
});
test("cookie security follows the app protocol and preserves the SDK's readable-cookie requirement", () => {
  expect(authCookieOptions("https://trace.example.test")).toEqual({ path: "/", sameSite: "lax", secure: true, httpOnly: false });
  expect(authCookieOptions("http://localhost:3000").secure).toBe(false);
});
test("PKCE callback uses the SDK and a pinned destination rather than incoming host or next", async () => {
  const result = await GET(new NextRequest("https://untrusted.example/auth/callback?code=controlled-code&next=https://evil.example"));
  expect(fixture.exchange).toHaveBeenCalledWith("controlled-code");
  // Default destination after sign-in is the lessons hub; query `next` is ignored.
  expect(result.headers.get("location")).toBe("https://trace.example.test/learn");
  expect(result.headers.get("cache-control")).toContain("no-store");
  expect(result.headers.get("referrer-policy")).toBe("no-referrer");
});
test.each(["signup", "recovery"])("confirmation/recovery link %s uses provider verification", async (type) => {
  const result = await GET(new NextRequest(`https://trace.example.test/auth/callback?type=${type}&token_hash=controlled-link`));
  expect(fixture.verify).toHaveBeenCalledWith({ type, token_hash: "controlled-link" });
  expect(result.headers.get("location")).toBe(`https://trace.example.test/${type === "recovery" ? "reset-password" : "account"}`);
});
test.each(["magiclink", "email", "sms", "invite"])("callback excludes %s login", async (type) => {
  const result = await GET(new NextRequest(`https://trace.example.test/auth/callback?type=${type}&token_hash=controlled-link`));
  expect(fixture.verify).not.toHaveBeenCalled();
  expect(result.headers.get("location")).toBe("https://trace.example.test/sign-in?auth_error=link");
});
test("provider callback errors never reflect provider details", async () => {
  const result = await GET(new NextRequest("https://trace.example.test/auth/callback?code=x&error=cancelled&error_description=untrusted"));
  expect(fixture.exchange).not.toHaveBeenCalled();
  expect(result.headers.get("location")).not.toContain("untrusted");
  fixture.exchange.mockResolvedValue({ error: {} });
  const failed = await GET(new NextRequest("https://trace.example.test/auth/callback?code=expired"));
  expect(failed.headers.get("location")).toContain("auth_error=link");
  fixture.exchange.mockRejectedValueOnce(new Error("private transport failure"));
  const outage = await GET(new NextRequest("https://trace.example.test/auth/callback?code=fixture"));
  expect(outage.headers.get("location")).toBe("https://trace.example.test/sign-in?auth_error=link");
});
test("server pages require verified claims and fail closed on invalid sessions or outages", async () => {
  expect(await RequireAccount({ children: "protected" })).toBe("protected");
  fixture.claims.mockResolvedValue({ data: null, error: {} });
  await expect(RequireAccount({ children: "protected" })).rejects.toThrow("redirected");
  fixture.claims.mockRejectedValue(new Error("provider unavailable"));
  await expect(RequireAccount({ children: "protected" })).rejects.toThrow("redirected");
  fixture.configured = false;
  await expect(RequireAccount({ children: "protected" })).rejects.toThrow("redirected");
  expect(fixture.redirect).toHaveBeenLastCalledWith("/sign-in");
});

test("only an allowlisted remembered destination is used after the OAuth round trip", async () => {
  const ok = new NextRequest("https://trace.example.test/auth/callback?code=fixture", { headers: { cookie: "trace_next=%2Faccount" } });
  expect((await GET(ok)).headers.get("location")).toBe("https://trace.example.test/account");
  for (const bad of ["https%3A%2F%2Fevil.example", "%2F%2Fevil.example", "%2Fsign-in", "%2Flearn%2F..%2F..%2Fx"]) {
    const request = new NextRequest("https://trace.example.test/auth/callback?code=fixture", { headers: { cookie: `trace_next=${bad}` } });
    expect((await GET(request)).headers.get("location")).toBe("https://trace.example.test/learn");
  }
});
test.each(["%25", "%2Flearn%25", "%252Faccount", "%E0%A4%A", "%C0%AFaccount"])("invalid remembered cookie %s falls back without decoding twice", async (cookie) => {
  const request = new NextRequest("https://trace.example.test/auth/callback?code=fixture", { headers: { cookie: `trace_next=${cookie}` } });
  const result = await GET(request);
  expect(result.status).toBe(303);
  expect(result.headers.get("location")).toBe("https://trace.example.test/learn");
  expect(result.cookies.get("trace_next")?.value).toBe("");
  expect(fixture.exchange).toHaveBeenCalledWith("fixture");
});

test("an invalid remembered cookie cannot break a provider-error redirect", async () => {
  const request = new NextRequest("https://trace.example.test/auth/callback?error=access_denied", { headers: { cookie: "trace_next=%25" } });
  const result = await GET(request);
  expect(result.status).toBe(303);
  expect(result.headers.get("location")).toBe("https://trace.example.test/sign-in?auth_error=cancelled");
  expect(result.cookies.get("trace_next")?.value).toBe("");
  expect(fixture.exchange).not.toHaveBeenCalled();
});

test("provider errors map to fixed, friendly message keys", async () => {
  const cancelled = await GET(new NextRequest("https://trace.example.test/auth/callback?error=access_denied&error_description=user+denied"));
  expect(cancelled.headers.get("location")).toBe("https://trace.example.test/sign-in?auth_error=cancelled");
  const disabled = await GET(new NextRequest("https://trace.example.test/auth/callback?error=invalid_request&error_code=validation_failed&error_description=Unsupported+provider%3A+provider+is+not+enabled"));
  expect(disabled.headers.get("location")).toBe("https://trace.example.test/sign-in?auth_error=provider");
});
