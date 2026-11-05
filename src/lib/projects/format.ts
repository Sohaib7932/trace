import type { RepositoryKnowledge } from "@/lib/api/github-projects";

export const SHA_PATTERN = /^[0-9a-f]{40}$/;
export const isCommitSha = (value: string) => SHA_PATTERN.test(value);
export const shortSha = (sha: string) => sha.slice(0, 7);

/** Most repositories added in one go. The server has no batch limit; this keeps the queue short and readable. */
export const MAX_SELECTION = 10;

const EXTENSIONS: Record<string, string> = {
  ts: "TypeScript", tsx: "TypeScript", js: "JavaScript", jsx: "JavaScript", mjs: "JavaScript", cjs: "JavaScript",
  py: "Python", go: "Go", rs: "Rust", java: "Java", kt: "Kotlin", rb: "Ruby", php: "PHP", cs: "C#", swift: "Swift",
  c: "C", h: "C", cpp: "C++", hpp: "C++", sql: "SQL", sh: "Shell", css: "CSS", scss: "CSS", html: "HTML",
  md: "Markdown", json: "JSON", yml: "YAML", yaml: "YAML", toml: "TOML",
};

export function languageOf(path: string): string | null {
  const extension = path.split(".").pop()?.toLowerCase() ?? "";
  return path.includes(".") ? EXTENSIONS[extension] ?? null : null;
}

/** Deterministic soft colours per language name (never random, so they match across pages). */
export function languageStyle(name: string): { backgroundColor: string; color: string } {
  let hash = 0;
  for (const character of name) hash = (hash * 31 + character.charCodeAt(0)) >>> 0;
  const hue = hash % 360;
  return { backgroundColor: `hsl(${hue} 70% 93%)`, color: `hsl(${hue} 55% 24%)` };
}

/** Languages found among the files Trace could read, most common first. Counts come from the real catalog. */
export function languagesOf(knowledge: RepositoryKnowledge | undefined): { name: string; files: number }[] {
  const counts = new Map<string, number>();
  for (const entry of knowledge?.catalog ?? []) {
    if (entry.kind !== "file" || !entry.content_included) continue;
    const name = languageOf(entry.path);
    if (name && name !== "Markdown" && name !== "JSON" && name !== "YAML" && name !== "TOML") counts.set(name, (counts.get(name) ?? 0) + 1);
  }
  return [...counts].map(([name, files]) => ({ name, files })).sort((a, b) => b.files - a.files || a.name.localeCompare(b.name)).slice(0, 5);
}

const REASONS: Record<string, string> = {
  excluded_path: "Secrets, build output and other excluded paths",
  unsupported_type: "Files that aren't plain text code",
  file_size: "Files over the size limit",
  invalid_content: "Files that couldn't be read as text",
  tree_budget: "The repository tree was larger than the limit",
  catalog_budget: "More files than the catalog limit",
  file_budget: "More files than the reading limit",
  source_budget: "More source than the reading limit",
  history_budget: "Only recent history was read",
  changed_files_budget: "Only some changed files were listed",
  request_deadline_budget: "Reading stopped at the time limit",
  truncated_tree: "GitHub returned a partial tree",
  unsupported_agent_format: "AI-agent logs in an unsupported format",
};
export const reasonLabel = (reason: string) => REASONS[reason] ?? reason.replaceAll("_", " ");

/** The commit a learner last used for a repository: a per-browser convenience, never sent anywhere else. */
const key = (connectionId: string) => `trace.project.sha.${connectionId}`;
export function loadSha(connectionId: string): string {
  try { const value = localStorage.getItem(key(connectionId)) ?? ""; return isCommitSha(value) ? value : ""; } catch { return ""; }
}
export function saveSha(connectionId: string, sha: string) {
  try { localStorage.setItem(key(connectionId), sha); } catch { /* storage unavailable: the field still works for this visit */ }
}

const SUPPORTED = ["Python", "TypeScript", "JavaScript", "Go", "Java", "C#", "Ruby", "PHP", "SQL"] as const;

/** The lesson language that fits most of these files, or null if none of them is a language Trace can teach. */
export function lessonLanguageFor(paths: string[]): string | null {
  const counts = new Map<string, number>();
  for (const path of paths) {
    const name = languageOf(path);
    if (name && (SUPPORTED as readonly string[]).includes(name)) counts.set(name, (counts.get(name) ?? 0) + 1);
  }
  return [...counts].sort((a, b) => b[1] - a[1])[0]?.[0] ?? null;
}
