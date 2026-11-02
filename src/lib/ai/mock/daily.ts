import type { Interest } from "../contracts";
import { mockGate } from "./controls";

/**
 * Demo-only interests and daily-exercise state, kept in this browser's localStorage.
 * Never sent to the backend and never written into real progress or the journey.
 */
export const interestCatalog: Interest[] = [
  { id: "notes-todos", label: "Notes & to-dos" },
  { id: "online-shop", label: "Online shop orders" },
  { id: "music", label: "Music playlists" },
  { id: "fitness", label: "Fitness tracking" },
  { id: "travel", label: "Travel bookings" },
  { id: "recipes", label: "Recipes" },
  { id: "sports", label: "Sports scores" },
  { id: "messaging", label: "Messaging apps" },
];

export const MAX_INTERESTS = 5;
const INTERESTS_KEY = "trace.demo.interests";
const DONE_KEY = "trace.demo.daily-done";

function read<T>(key: string, fallback: T): T {
  try { const raw = localStorage.getItem(key); return raw ? (JSON.parse(raw) as T) : fallback; } catch { return fallback; }
}
function write(key: string, value: unknown) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* storage unavailable: demo state lasts for this visit */ }
}

export const mockDaily = {
  async interests(): Promise<Interest[]> { await mockGate(); return interestCatalog; },
  getSaved(): string[] | null { return read<string[] | null>(INTERESTS_KEY, null); },
  async save(ids: string[]): Promise<string[]> {
    if (ids.length > MAX_INTERESTS) throw new Error(`Choose up to ${MAX_INTERESTS} interests.`);
    const known = ids.filter((id) => interestCatalog.some((i) => i.id === id));
    write(INTERESTS_KEY, known);
    return known;
  },
  /** Demo exercise ids marked done in this browser (only demo exercises, never real lessons). */
  doneIds(): string[] { return read<string[]>(DONE_KEY, []); },
  markDone(id: string) { write(DONE_KEY, [...new Set([...mockDaily.doneIds(), id])]); },
  reset() { write(DONE_KEY, []); },
};
