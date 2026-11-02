/**
 * 30 sample support questions with the help-article ids that should answer them.
 * Generated from the local help set (src/content/support/articles.ts) as a starting
 * evaluation set for the backend RAG (see docs/frontend-api-requests.md). `null` means
 * no article should match: the right answer is "I'm not sure".
 */
export const supportEvalSet: { question: string; expected: string | null }[] = [
  { question: "How do I sign up?", expected: "sign-up" },
  { question: "How do I create an account with my email?", expected: "sign-up" },
  { question: "I never got the confirmation email", expected: "sign-up" },
  { question: "How do I log in?", expected: "sign-in-reset" },
  { question: "I forgot my password", expected: "sign-in-reset" },
  { question: "My reset link expired", expected: "sign-in-reset" },
  { question: "I can't sign in with Google", expected: "google-sign-in" },
  { question: "Google sign-in says it isn't set up", expected: "google-sign-in" },
  { question: "The Google callback failed", expected: "google-sign-in" },
  { question: "Will my guest progress be kept when I sign in?", expected: "guest-history" },
  { question: "How do I claim my guest history?", expected: "guest-history" },
  { question: "Can two histories be merged?", expected: "guest-history" },
  { question: "Where is my progress?", expected: "find-progress" },
  { question: "Where can I see my saved history?", expected: "find-progress" },
  { question: "How do lessons work?", expected: "lessons-navigation" },
  { question: "Why is the tasks lesson locked?", expected: "lessons-navigation" },
  { question: "What does verification check?", expected: "verification" },
  { question: "Why did my request return 422?", expected: "verification" },
  { question: "Verification unavailable error, is it my mistake?", expected: "verification-errors" },
  { question: "The check is broken, what should I do?", expected: "verification-errors" },
  { question: "What is a fixture hint?", expected: "fixture-hints" },
  { question: "How many hints do I get?", expected: "fixture-hints" },
  { question: "How do follow-ups work?", expected: "follow-ups" },
  { question: "When is my follow-up due?", expected: "follow-ups" },
  { question: "Are there daily exercises?", expected: "daily-exercises" },
  { question: "Is there a limit of three new exercises a day?", expected: "daily-exercises" },
  { question: "My progress disappeared on localhost", expected: "local-setup" },
  { question: "Should I share my secret key or password with support?", expected: "safety" },
  { question: "What's the weather tomorrow?", expected: null },
  { question: "Write my homework essay", expected: null },
];
