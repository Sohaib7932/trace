/**
 * Languages and frameworks Trace recognises in a learner's message, so the composer can
 * work from plain words. Lessons created from a request are never run on Trace's server:
 * multiple-choice style answers are checked against an answer key on the server and
 * "explain" answers are practice only (see src/lib/learning/verification.ts).
 */
export type LessonLanguage = {
  id: string;
  label: string;
  /** Matches the language when the learner names it. */
  pattern: RegExp;
  frameworks: readonly { label: string; pattern: RegExp }[];
  /** Short highlight name for code windows; "plain" means monospace without colours. */
  highlight: string;
};

export const lessonLanguages: readonly LessonLanguage[] = [
  { id: "python", label: "Python", pattern: /\bpython\b|\bpy\b/i, highlight: "python", frameworks: [
    { label: "FastAPI", pattern: /\bfast\s?api\b/i }, { label: "Flask", pattern: /\bflask\b/i },
    { label: "Django", pattern: /\bdjango\b/i }, { label: "Pydantic", pattern: /\bpydantic\b/i }] },
  { id: "typescript", label: "TypeScript", pattern: /\btype\s?script\b|\bts\b/i, highlight: "typescript", frameworks: [] },
  { id: "javascript", label: "JavaScript", pattern: /\bjava\s?script\b|\bjs\b|\bnode\.?js\b/i, highlight: "javascript", frameworks: [
    { label: "Express", pattern: /\bexpress(\.js)?\b/i }, { label: "React", pattern: /\breact\b/i }, { label: "Next.js", pattern: /\bnext\.?js\b/i }] },
  { id: "go", label: "Go", pattern: /\bgolang\b|\bGo\b/, highlight: "go", frameworks: [{ label: "Gin", pattern: /\bgin\b/i }] },
  { id: "java", label: "Java", pattern: /\bjava\b(?!\s?script)/i, highlight: "java", frameworks: [{ label: "Spring Boot", pattern: /\bspring(\s?boot)?\b/i }] },
  { id: "csharp", label: "C#", pattern: /c#|\bc\s?sharp\b|\.net\b/i, highlight: "csharp", frameworks: [{ label: "ASP.NET Core", pattern: /\basp\.?net\b/i }] },
  { id: "ruby", label: "Ruby", pattern: /\bruby\b/i, highlight: "ruby", frameworks: [{ label: "Rails", pattern: /\brails\b/i }] },
  { id: "php", label: "PHP", pattern: /\bphp\b/i, highlight: "php", frameworks: [{ label: "Laravel", pattern: /\blaravel\b/i }] },
  { id: "sql", label: "SQL", pattern: /\bsql\b|\bpostgres(ql)?\b|\bmysql\b|\bsqlite\b/i, highlight: "sql", frameworks: [] },
];

export type DetectedStack = { language?: LessonLanguage; framework?: string };

/**
 * The language and framework a message mentions. A framework alone implies its language
 * ("FastAPI" means Python). Nothing mentioned: both undefined.
 */
export function detectStack(text: string): DetectedStack {
  const named = lessonLanguages.find((l) => l.pattern.test(text));
  if (named) {
    const framework = named.frameworks.find((f) => f.pattern.test(text));
    return { language: named, framework: framework?.label };
  }
  for (const language of lessonLanguages) {
    const framework = language.frameworks.find((f) => f.pattern.test(text));
    if (framework) return { language, framework: framework.label };
  }
  return {};
}

/** The table entry for a stored lesson language (id, label or a recognisable name). */
export function findLanguageById(name: string): LessonLanguage | undefined {
  const key = name.trim().toLowerCase();
  return lessonLanguages.find((l) => l.id === key || l.label.toLowerCase() === key) ?? detectStack(name).language;
}
