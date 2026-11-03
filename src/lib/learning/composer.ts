import { looksSecret } from "@/components/ai/use-dialog";
import { detectStack } from "@/content/lesson-languages";
import type { CustomLessonRequestCreate } from "@/lib/api/client";

/**
 * The lesson composer is one chat-style message: the learner explains, in their own words,
 * what lesson they want. Options (language, level, number of lessons, practice styles) are
 * optional and hidden under "Fine-tune"; by default they're read from the message.
 * Kept in this browser as a draft.
 */
export type PracticeStyle = "predict_output" | "find_bug" | "multiple_choice" | "explain";
export type ComposerDraft = {
  prompt: string;
  /** Empty means "use the language mentioned in the message". */
  language: string;
  level: "beginner" | "intermediate" | "advanced";
  lessonCount: 1 | 2 | 3;
  styles: PracticeStyle[];
};

export const PROMPT_MIN = 10;
export const PROMPT_MAX = 1000;
export const ALL_STYLES: readonly PracticeStyle[] = ["predict_output", "find_bug", "multiple_choice", "explain"];

export const DEFAULT_DRAFT: ComposerDraft = { prompt: "", language: "", level: "beginner", lessonCount: 1, styles: [...ALL_STYLES] };

export const levelLabels: Record<ComposerDraft["level"], string> = { beginner: "Beginner", intermediate: "Intermediate", advanced: "Advanced" };
export const styleLabels: Record<PracticeStyle, string> = {
  predict_output: "Predict the output",
  find_bug: "Find the bug",
  multiple_choice: "Multiple choice",
  explain: "Explain in your words",
};

export const examplePrompts = [
  "Teach me how FastAPI validates a request body, with exercises where I predict the response.",
  "I want to understand why my Express route sometimes sends two responses.",
  "Help me debug SQL joins that return duplicate rows. I'm a beginner.",
  "Show me how async and await change the order my Python code runs in.",
] as const;

export const exampleChips = [
  { label: "FastAPI request checks", prompt: examplePrompts[0] },
  { label: "Express double response", prompt: examplePrompts[1] },
  { label: "SQL duplicate rows", prompt: examplePrompts[2] },
  { label: "Python async order", prompt: examplePrompts[3] },
] as const;

/** A plain-language problem with the message, or null when it can be sent. */
export function validatePrompt(text: string): string | null {
  const prompt = text.trim();
  if (prompt.length < PROMPT_MIN) return `Describe what you want to learn in at least ${PROMPT_MIN} characters.`;
  if (prompt.length > PROMPT_MAX) return `Keep it under ${PROMPT_MAX} characters.`;
  if (looksSecret(prompt)) return "This looks like a password or secret key. Remove it before continuing.";
  return null;
}

/** The language the lesson will use: the Fine-tune choice, else the one named in the message. */
export function resolvedLanguage(draft: ComposerDraft): { language: string; framework: string | null } | null {
  const chosen = draft.language.trim();
  const stack = detectStack(draft.prompt);
  if (chosen) return { language: chosen.slice(0, 40), framework: stack.framework ?? null };
  if (stack.language) return { language: stack.language.label, framework: stack.framework ?? null };
  return null;
}

export type DraftProblem = { field: "prompt" | "language" | "styles"; message: string };

/** Everything that blocks sending, in the order the learner should fix it. */
export function draftProblems(draft: ComposerDraft): DraftProblem[] {
  const problems: DraftProblem[] = [];
  const prompt = validatePrompt(draft.prompt);
  if (prompt) problems.push({ field: "prompt", message: prompt });
  if (!resolvedLanguage(draft)) problems.push({ field: "language", message: "Which language? Mention it in your message, or choose it under Fine-tune." });
  else if (looksSecret(draft.language)) problems.push({ field: "language", message: "Remove secrets from the language field." });
  if (draft.styles.length === 0) problems.push({ field: "styles", message: "Choose at least one practice style." });
  return problems;
}

/** The exact request body sent to POST /custom-lessons/requests. */
export function requestBody(draft: ComposerDraft): CustomLessonRequestCreate {
  const stack = resolvedLanguage(draft);
  if (!stack) throw new Error("A language is required");
  return {
    topic: draft.prompt.trim(),
    language: stack.language,
    framework: stack.framework,
    level: draft.level,
    goal: "understand",
    lesson_count: draft.lessonCount,
    practice_styles: ALL_STYLES.filter((style) => draft.styles.includes(style)),
  };
}

/** A short working title for the live preview, from the learner's own words. */
export function previewTitle(prompt: string): string {
  const words = prompt.trim().replace(/\s+/g, " ");
  if (!words) return "Your lesson";
  return words.length > 72 ? `${words.slice(0, 71).trimEnd()}…` : words;
}

const DRAFT_KEY = "trace.composer.draft";

/** Restores a saved draft (also older drafts with fewer fields), ignoring anything malformed. */
export function loadDraft(): ComposerDraft | null {
  try {
    const raw = localStorage.getItem(DRAFT_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<Record<keyof ComposerDraft, unknown>>;
    if (typeof parsed.prompt !== "string") return null;
    return {
      prompt: parsed.prompt,
      language: typeof parsed.language === "string" ? parsed.language : "",
      level: parsed.level === "intermediate" || parsed.level === "advanced" ? parsed.level : "beginner",
      lessonCount: parsed.lessonCount === 2 || parsed.lessonCount === 3 ? parsed.lessonCount : 1,
      styles: Array.isArray(parsed.styles) && parsed.styles.length
        ? ALL_STYLES.filter((style) => (parsed.styles as unknown[]).includes(style))
        : [...ALL_STYLES],
    };
  } catch { return null; }
}

export function saveDraft(draft: ComposerDraft): boolean {
  try { localStorage.setItem(DRAFT_KEY, JSON.stringify(draft)); return true; } catch { return false; }
}

export function clearDraft() {
  try { localStorage.removeItem(DRAFT_KEY); } catch { /* storage unavailable */ }
}
