/**
 * Project paths have no server-side progress yet, so a learner's locked answers are kept in this browser only
 * (per account, repository, commit and path). Nothing here is sent anywhere, and nothing counts as completion
 * on the server or on the leaderboard.
 */
export type StepRecord = { text: string; lockedAt: string };
export type PathProgress = Record<number, StepRecord>;

const key = (owner: string | null, connectionId: string, sha: string, pathId: string) => `trace.project.progress.${owner ?? "guest"}.${connectionId}.${sha}.${pathId}`;

export function loadProgress(owner: string | null, connectionId: string, sha: string, pathId: string): PathProgress {
  try {
    const raw = localStorage.getItem(key(owner, connectionId, sha, pathId));
    const value: unknown = raw ? JSON.parse(raw) : {};
    if (!value || typeof value !== "object") return {};
    const result: PathProgress = {};
    for (const [index, record] of Object.entries(value as Record<string, unknown>)) {
      const r = record as Partial<StepRecord> | null;
      if (r && typeof r.text === "string" && typeof r.lockedAt === "string" && /^\d+$/.test(index)) result[Number(index)] = { text: r.text.slice(0, 4000), lockedAt: r.lockedAt };
    }
    return result;
  } catch { return {}; }
}

export function saveProgress(owner: string | null, connectionId: string, sha: string, pathId: string, progress: PathProgress) {
  try { localStorage.setItem(key(owner, connectionId, sha, pathId), JSON.stringify(progress)); } catch { /* storage unavailable: progress lasts for this visit only */ }
}
