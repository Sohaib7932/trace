/**
 * Shared wording for how a lesson is checked. Use these strings everywhere a verification
 * badge or explanation appears, so "checked on a real server" is only ever said for
 * `server_verified` (the deterministic backend run). AI drafts and explains; it never checks.
 */
export type VerificationMode = "server_verified" | "answer_key" | "practice_only";

export const VERIFICATION_MODES: readonly VerificationMode[] = ["server_verified", "answer_key", "practice_only"];

export const verificationCopy: Record<VerificationMode, { label: string; detail: string }> = {
  server_verified: {
    label: "Checked on a real server",
    detail: "Trace runs your change against a real server and shows what it returned.",
  },
  answer_key: {
    label: "Checked against an answer key",
    detail: "Your answer is compared with a prepared answer. Your code isn't run.",
  },
  practice_only: {
    label: "Practice only",
    detail: "There's no automatic check. You compare your work with the explanation.",
  },
};

export const isVerificationMode = (value: unknown): value is VerificationMode =>
  typeof value === "string" && (VERIFICATION_MODES as readonly string[]).includes(value);
