/**
 * Local help set for the Trace Help DEMO (mock mode only). Written from the real product
 * behaviour and the draft support package in docs/support-drafts/ (unapproved drafts:
 * this set is a demo stand-in, not the approved production corpus, which the backend
 * will own). The mock answers only from these articles and cites them by id; it never
 * invents sources.
 */
export type HelpArticle = {
  id: string;
  title: string;
  /** Plain-language answer text, 2–4 short sentences. */
  body: string;
  /** Internal route that helps with this topic. */
  link: string;
  keywords: string[];
  /** Draft this article follows, if any. */
  draft?: string;
};

export const helpArticles: HelpArticle[] = [
  {
    id: "trace-overview",
    title: "What Trace is",
    body: "Trace helps you read, predict, change and verify real Python/FastAPI code yourself. You predict what a request does, make one focused change, and the server checks what really happened. Hints and explanations can help you reason, but only verification decides whether a change works.",
    link: "/",
    keywords: ["trace", "what", "about", "overview", "product", "learn", "fastapi", "python"],
    draft: "01-trace-overview.md",
  },
  {
    id: "sign-up",
    title: "Creating an account",
    body: "Choose Sign up, enter your email and a password of at least 12 characters, then open the confirmation link we email you. You can keep learning as a guest without an account. An account lets you keep your progress across devices.",
    link: "/sign-up",
    keywords: ["sign", "up", "signup", "register", "registration", "account", "create", "email", "confirm", "confirmation", "password"],
    draft: "02-registration-authentication.md",
  },
  {
    id: "sign-in-reset",
    title: "Signing in and resetting your password",
    body: "Use Sign in with your email and password. If you forgot it, choose Forgot password: we send a reset link if an account can receive one, without saying whether the email exists. Expired or used links need a new request.",
    link: "/sign-in",
    keywords: ["sign", "in", "signin", "login", "log", "forgot", "reset", "password", "link", "expired"],
    draft: "02-registration-authentication.md",
  },
  {
    id: "google-sign-in",
    title: "Problems signing in with Google",
    body: "If Google sign-in is cancelled or the callback fails, start a fresh sign-in from the Sign in page. If you see \"Google sign-in isn't set up on this site yet\", use email and password instead, or keep learning as a guest. Choosing a different Google identity can create a different Trace account; accounts are never merged automatically.",
    link: "/sign-in",
    keywords: ["google", "oauth", "sign", "in", "callback", "cancelled", "can't", "cannot", "fails", "error", "set", "up"],
    draft: "03-google-authentication.md",
  },
  {
    id: "guest-history",
    title: "Keeping guest progress when you sign in",
    body: "If you learned as a guest in this browser and then sign in, Trace asks whether to keep that guest history with your account. Choose Keep my guest progress to move it. If you start fresh instead, the two histories stay separate; Trace never merges them automatically.",
    link: "/account",
    keywords: ["guest", "history", "histories", "claim", "keep", "progress", "merge", "merged", "sign", "account", "lost", "browser"],
    draft: "02-registration-authentication.md",
  },
  {
    id: "find-progress",
    title: "Where to find your progress",
    body: "The Lessons page shows each lesson's status and where you left off. Your account page lists your saved predictions, attempts, hints and what the server observed. Progress is factual: it shows what you did, not a score.",
    link: "/learn",
    keywords: ["where", "progress", "saved", "find", "see", "status", "account", "lessons", "dashboard"],
    draft: "07-progress-retrieval.md",
  },
  {
    id: "lessons-navigation",
    title: "How lessons work",
    body: "Start with the Notes lesson. Lock a prediction, change the field in the code, and run the check. Completing Notes unlocks the Tasks lesson, which uses the same idea in new code. An active session keeps the lesson version it started with.",
    link: "/learn",
    keywords: ["lesson", "lessons", "start", "unlock", "locked", "notes", "tasks", "transfer", "next", "navigation"],
    draft: "04-learning-navigation.md",
  },
  {
    id: "verification",
    title: "Predictions, attempts and verification",
    body: "Your first prediction is locked and kept. Each change you try is a separate numbered attempt. Verification sends the request to a real server and reads the database separately: the HTTP status, the response, validation errors, the row count and the saved values must all agree.",
    link: "/learn/fastapi-payload-mismatch",
    keywords: ["prediction", "attempt", "verify", "verification", "check", "evidence", "422", "201", "rejected", "row", "database", "correct"],
    draft: "05-prediction-attempts-verification.md",
  },
  {
    id: "verification-errors",
    title: "Why a verification error is not your mistake",
    body: "\"Verification unavailable\" means the checking system itself had a problem, not that your change was wrong. Your attempt is kept. Reload the lesson to see your saved work, then choose Check again.",
    link: "/learn",
    keywords: ["verification", "error", "unavailable", "infrastructure", "mistake", "failed", "server", "check", "again", "broken"],
    draft: "09-technical-problems.md",
  },
  {
    id: "fixture-hints",
    title: "What a fixture hint is",
    body: "Hints in lessons are fixture guidance: short, pre-written clues, not live AI. You get up to three per session after you lock your prediction. Each request is recorded, even if a hint is unavailable. Hints help you reason; they never mark a change as correct.",
    link: "/learn/fastapi-payload-mismatch",
    keywords: ["hint", "hints", "fixture", "guidance", "clue", "help", "three", "ai", "what"],
    draft: "06-hints-explanations.md",
  },
  {
    id: "follow-ups",
    title: "How follow-ups work",
    body: "When you complete the Tasks lesson, Trace schedules two short follow-up questions: 24 hours and 7 days later. Dates come from the server. A missed follow-up stays open until you answer, and no reminder email is sent.",
    link: "/account?tab=follow-ups",
    keywords: ["follow", "up", "followup", "follow-up", "follow-ups", "checkpoint", "revisit", "retrieval", "24", "hours", "7", "days", "due", "when"],
    draft: "07-progress-retrieval.md",
  },
  {
    id: "daily-exercises",
    title: "Daily exercises",
    body: "Daily exercises are a design preview and are not connected yet. The planned rule is up to three new exercises per day, but the day boundary and timezone haven't been decided. Hints, retries and follow-ups don't use up new-exercise slots.",
    link: "/today",
    keywords: ["daily", "today", "three", "exercises", "new", "quota", "limit", "day", "timezone", "assignment"],
    draft: "08-daily-availability.md",
  },
  {
    id: "local-setup",
    title: "Running Trace locally: cookies and the same hostname",
    body: "Guest progress uses a cookie, so the app and the API must use the same hostname: localhost with localhost, or 127.0.0.1 with 127.0.0.1. If progress seems to disappear, check you opened the same address as before. Clearing site data removes the guest cookie; Trace can't recover a lost guest identity.",
    link: "/learn",
    keywords: ["cookie", "cookies", "localhost", "127.0.0.1", "hostname", "local", "setup", "disappeared", "lost", "progress", "missing"],
    draft: "09-technical-problems.md",
  },
  {
    id: "safety",
    title: "Keeping your account safe",
    body: "Never share your password, reset links or secret keys, including in this chat. Trace Help can't change your account, reset passwords or see other learners' records. Use the Sign in and Forgot password pages for account changes.",
    link: "/account",
    keywords: ["password", "secret", "key", "token", "share", "security", "safe", "delete", "change", "account"],
    draft: "10-human-escalation.md",
  },
];
