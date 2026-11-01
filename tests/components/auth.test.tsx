import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";
import { AuthForm } from "@/components/auth/auth-form";
import { AccountLink } from "@/components/auth/account-link";

const fixture = vi.hoisted(() => ({
  configured: true,
  auth: { signUp: vi.fn(), signInWithPassword: vi.fn(), signInWithOAuth: vi.fn(),
    resetPasswordForEmail: vi.fn(), updateUser: vi.fn(), signOut: vi.fn(), resend: vi.fn(),
    getUser: vi.fn(), onAuthStateChange: vi.fn() },
  me: vi.fn(), claim: vi.fn(), push: vi.fn(), refresh: vi.fn(),
}));
vi.mock("@/lib/supabase/browser", () => ({ browserAuth: () => fixture.configured ? { auth: fixture.auth } : null }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: fixture.push, refresh: fixture.refresh }) }));
vi.mock("@/lib/api/client", async (original) => ({ ...await original<typeof import("@/lib/api/client")>(), accountApi: { me: fixture.me, claim: fixture.claim } }));
const account = { user_id: "trace-user-fixture", created_at: "2026-10-31T00:00:00Z", status: "active", roles: ["learner", "creator"], learner_id: null, anonymous_history_available: true };

beforeEach(() => {
  vi.clearAllMocks(); fixture.configured = true;
  fixture.auth.signUp.mockResolvedValue({ data: { session: null }, error: null });
  for (const method of [fixture.auth.signInWithPassword, fixture.auth.signInWithOAuth,
    fixture.auth.resetPasswordForEmail, fixture.auth.updateUser, fixture.auth.signOut, fixture.auth.resend]) method.mockResolvedValue({ error: null });
  fixture.auth.getUser.mockResolvedValue({ data: { user: { email: "learner@example.test", email_confirmed_at: "2026-10-31", identities: [{ provider: "email" }, { provider: "google" }] } } });
  fixture.auth.onAuthStateChange.mockReturnValue({ data: { subscription: { unsubscribe: vi.fn() } } });
  fixture.me.mockResolvedValue(account); fixture.claim.mockResolvedValue({ claimed: true });
});
async function credentials(mode: "sign-up" | "sign-in" | "reset-password", confirm = "Controlled-password-12") {
  render(<AuthForm mode={mode} />);
  const user = userEvent.setup();
  if (mode !== "reset-password") await user.type(screen.getByLabelText("Email address"), "learner@example.test");
  await user.type(screen.getByLabelText(mode === "reset-password" ? "New password" : "Password", { exact: true }), "Controlled-password-12");
  if (mode !== "sign-in") await user.type(screen.getByLabelText("Confirm password", { exact: true }), confirm);
  return user;
}

test("registration rejects mismatched passwords before any provider request", async () => {
  const user = await credentials("sign-up", "Different-password-13");
  await user.click(screen.getByRole("button", { name: "Create account" }));
  expect(screen.getByRole("status")).toHaveTextContent("Passwords must match");
  expect(fixture.auth.signUp).not.toHaveBeenCalled();
});
test("registration requires a provider confirmation and shows the inbox screen with a resend cooldown", async () => {
  const user = await credentials("sign-up");
  await user.click(screen.getByRole("button", { name: "Create account" }));
  expect(await screen.findByRole("status")).toHaveTextContent("Check your email");
  expect(screen.getByRole("heading", { name: "Check your inbox" })).toBeVisible();
  expect(screen.getByText("learner@example.test")).toBeVisible();
  expect(fixture.auth.signUp).toHaveBeenCalledWith(expect.objectContaining({ options: { emailRedirectTo: expect.stringContaining("/auth/callback?type=signup") } }));
  // Resend waits 30 seconds after sending, so it can't be hammered.
  expect(screen.getByRole("button", { name: /Resend available in 30s/ })).toBeDisabled();
  expect(fixture.auth.resend).not.toHaveBeenCalled();
});
test("an unconfirmed sign-in offers a safe resend", async () => {
  fixture.auth.signInWithPassword.mockResolvedValue({ error: { code: "email_not_confirmed" } });
  const user = await credentials("sign-in");
  await user.click(screen.getByRole("button", { name: "Sign in" }));
  await user.click(await screen.findByRole("button", { name: "Resend confirmation email" }));
  expect(fixture.auth.resend).toHaveBeenCalledWith(expect.objectContaining({ type: "signup", email: "learner@example.test" }));
});
test("a provider without confirmation enabled is reported instead of a claimed verification", async () => {
  fixture.auth.signUp.mockResolvedValue({ data: { session: {} }, error: null });
  const user = await credentials("sign-up");
  await user.click(screen.getByRole("button", { name: "Create account" }));
  expect(await screen.findByRole("status")).toHaveTextContent("confirmation is not enabled");
  expect(fixture.auth.signOut).toHaveBeenCalled();
});
test("email login uses the SDK and goes to the lessons hub by default", async () => {
  const user = await credentials("sign-in");
  await user.click(screen.getByRole("button", { name: "Sign in" }));
  expect(fixture.auth.signInWithPassword).toHaveBeenCalledWith({ email: "learner@example.test", password: "Controlled-password-12" });
  expect(fixture.push).toHaveBeenCalledWith("/learn");
  expect(fixture.refresh).toHaveBeenCalled();
});
test.each([["/account", "/account"], ["https://evil.example", "/learn"], ["//evil.example", "/learn"], ["/sign-in", "/learn"]])("sign-in honours only a safe next (%s -> %s)", async (next, expected) => {
  render(<AuthForm mode="sign-in" next={next} />);
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Email address"), "learner@example.test");
  await user.type(screen.getByLabelText("Password", { exact: true }), "Controlled-password-12");
  await user.click(screen.getByRole("button", { name: "Sign in" }));
  expect(fixture.push).toHaveBeenCalledWith(expected);
});
test("fields validate on blur with messages tied to the input", async () => {
  render(<AuthForm mode="sign-up" />);
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Email address"), "not-an-email");
  await user.type(screen.getByLabelText("Password", { exact: true }), "short");
  await user.click(screen.getByLabelText("Confirm password"));
  expect(screen.getByLabelText("Email address")).toHaveAttribute("aria-invalid", "true");
  expect(screen.getByText("Enter an email address like name@example.com.")).toBeVisible();
  expect(screen.getByText("Use at least 12 characters.")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Show password" }));
  expect(screen.getByLabelText("Password", { exact: true })).toHaveAttribute("type", "text");
});
test("a disabled Google provider shows a clear message instead of a blank redirect", async () => {
  vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", "http://localhost:54321");
  vi.stubEnv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY", "sb_publishable_test_fixture");
  vi.stubEnv("NEXT_PUBLIC_SITE_URL", window.location.origin);
  const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ external: { google: false } })));
  render(<AuthForm mode="sign-in" />);
  await userEvent.click(screen.getByRole("button", { name: "Continue with Google" }));
  expect(await screen.findByRole("status")).toHaveTextContent("Google sign-in isn't set up on this site yet");
  expect(fixture.auth.signInWithOAuth).not.toHaveBeenCalled();
  fetchSpy.mockRestore(); vi.unstubAllEnvs();
});
test.each(["invalid_credentials", "email_not_confirmed"])("login safely handles %s", async (code) => {
  fixture.auth.signInWithPassword.mockResolvedValue({ error: { code, message: "private provider text" } });
  const user = await credentials("sign-in");
  await user.click(screen.getByRole("button", { name: "Sign in" }));
  expect(await screen.findByRole("status")).toHaveTextContent(code === "email_not_confirmed" ? "Confirm your email" : "could not be verified");
  expect(screen.queryByText("private provider text")).toBeNull();
  expect(fixture.push).not.toHaveBeenCalled();
});
test("Google starts the supported SDK redirect and cancelled callbacks show safe guidance", async () => {
  render(<AuthForm mode="sign-in" callbackError />);
  expect(screen.getByRole("status")).toHaveTextContent("cancelled");
  await userEvent.click(screen.getByRole("button", { name: "Continue with Google" }));
  expect(fixture.auth.signInWithOAuth).toHaveBeenCalledWith({ provider: "google", options: { redirectTo: expect.stringContaining("/auth/callback") } });
});
test("forgot-password requests a recovery link without revealing account existence", async () => {
  render(<AuthForm mode="forgot-password" />);
  await userEvent.type(screen.getByLabelText("Email address"), "unknown@example.test");
  await userEvent.click(screen.getByRole("button", { name: "Send reset link" }));
  expect(await screen.findByRole("status")).toHaveTextContent("If an account");
  expect(fixture.auth.resetPasswordForEmail).toHaveBeenCalledWith("unknown@example.test", { redirectTo: expect.stringContaining("type=recovery") });
});
test("reset uses provider password update and signs out afterwards", async () => {
  const user = await credentials("reset-password");
  await user.click(screen.getByRole("button", { name: "Change password" }));
  expect(fixture.auth.updateUser).toHaveBeenCalledWith({ password: "Controlled-password-12" });
  expect(fixture.auth.signOut).toHaveBeenCalled(); expect(fixture.push).toHaveBeenCalledWith("/sign-in");
});
test("expired reset errors do not navigate or invent a successful change", async () => {
  fixture.auth.updateUser.mockResolvedValue({ error: { code: "session_not_found" } });
  const user = await credentials("reset-password");
  await user.click(screen.getByRole("button", { name: "Change password" }));
  expect(await screen.findByRole("status")).toHaveTextContent("Request a new reset link");
  expect(fixture.push).not.toHaveBeenCalled();
});
test("unconfigured installations retain accessible guest learning and disabled sign-in", () => {
  fixture.configured = false; render(<AuthForm mode="sign-in" />);
  expect(screen.getByRole("alert")).toHaveTextContent("not configured");
  expect(screen.getByRole("button", { name: "Sign in" })).toBeDisabled();
});
test("account navigation tracks SDK refresh and sign-out events and unsubscribes", async () => {
  const view = render(<AccountLink />);
  // Until the session is read, the link is hidden rather than showing a possibly wrong label.
  expect(screen.queryByRole("link")).toBeNull();
  const callback = fixture.auth.onAuthStateChange.mock.calls[0][0];
  act(() => callback("INITIAL_SESSION", null));
  expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/sign-in");
  act(() => callback("TOKEN_REFRESHED", {}));
  expect(screen.getByRole("link", { name: "Account" })).toHaveAttribute("href", "/account");
  act(() => callback("SIGNED_OUT", null));
  expect(screen.getByRole("link", { name: "Sign in" })).toBeVisible();
  const unsubscribe = fixture.auth.onAuthStateChange.mock.results[0].value.data.subscription.unsubscribe;
  view.unmount(); expect(unsubscribe).toHaveBeenCalled();
});
