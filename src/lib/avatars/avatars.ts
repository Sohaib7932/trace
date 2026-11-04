/**
 * Trace's own avatar set: friendly, abstract characters (orbs, planets, robots, geometric
 * animals, pixel faces, a rocket) on soft backgrounds in the brand palette. Original artwork,
 * no real faces. `avatar_id` values outside this allowlist are ignored everywhere they are
 * read or written; ids from the first set are mapped to a current one when read.
 */

export type AvatarDesign = { id: string; label: string; bg: [string, string] };

export const AVATARS: readonly AvatarDesign[] = [
  { id: "orb-sunset", label: "Sunset orb", bg: ["#ffe6d2", "#f9bf94"] },
  { id: "planet-ember", label: "Ember planet", bg: ["#fff0cf", "#f5cf86"] },
  { id: "robot-coral", label: "Coral robot", bg: ["#ffe1d9", "#f6a892"] },
  { id: "fox-geo", label: "Geometric fox", bg: ["#ffe9d6", "#f7c49a"] },
  { id: "pixel-smile", label: "Pixel smile", bg: ["#fff3d9", "#f6d98f"] },
  { id: "planet-teal", label: "Teal planet", bg: ["#dcf1ee", "#a6d9d2"] },
  { id: "owl-geo", label: "Geometric owl", bg: ["#ece8f8", "#c9c0ea"] },
  { id: "robot-indigo", label: "Indigo robot", bg: ["#e3e6fa", "#b7bff0"] },
  { id: "orb-aurora", label: "Aurora orb", bg: ["#dcf0f1", "#b2d8f0"] },
  { id: "cat-geo", label: "Geometric cat", bg: ["#e9ecf1", "#c6ccd8"] },
  { id: "pixel-ghost", label: "Pixel ghost", bg: ["#e8ecf4", "#c5cde0"] },
  { id: "rocket-amber", label: "Amber rocket", bg: ["#ffeccc", "#f8c981"] },
  { id: "planet-coral", label: "Coral planet", bg: ["#ffe3dc", "#f3b0a2"] },
  { id: "orb-slate", label: "Slate orb", bg: ["#eceef2", "#cfd3dc"] },
] as const;

export const AVATAR_IDS: readonly string[] = AVATARS.map((avatar) => avatar.id);

/** Ids from the first avatar set, and the current avatar each one now shows. */
const LEGACY: Record<string, string> = {
  "apricot-round": "orb-sunset",
  "peach-squircle": "robot-coral",
  "rose-drop": "planet-coral",
  "amber-cloud": "rocket-amber",
  "sage-leaf": "planet-teal",
  "plum-pebble": "robot-indigo",
  "sky-bean": "orb-aurora",
  "coral-round": "fox-geo",
  "sand-pebble": "cat-geo",
  "mint-drop": "pixel-smile",
  "terracotta-squircle": "pixel-smile",
  "lilac-cloud": "owl-geo",
  "honey-bean": "pixel-ghost",
  "slate-leaf": "orb-slate",
};

/** A current id, or the mapped current id for an old one; anything else is null. */
export function normalizeAvatarId(value: unknown): string | null {
  if (typeof value !== "string") return null;
  if (AVATAR_IDS.includes(value)) return value;
  return Object.hasOwn(LEGACY, value) ? LEGACY[value] : null;
}

/** Strict: only current ids may be saved. */
export const isAvatarId = (value: unknown): value is string => typeof value === "string" && AVATAR_IDS.includes(value);

export const avatarById = (id: string) => AVATARS.find((avatar) => avatar.id === id);

/** FNV-1a: a stable avatar for a stable id (never random, never a letter). */
export function defaultAvatarId(seed: string): string {
  let hash = 0x811c9dc5;
  for (let i = 0; i < seed.length; i++) {
    hash ^= seed.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return AVATARS[(hash >>> 0) % AVATARS.length].id;
}

/** The chosen avatar if it is on the allowlist (old ids mapped), else the default for `seed`. */
export function resolveAvatarId(chosen: unknown, seed: string): string {
  return normalizeAvatarId(chosen) ?? defaultAvatarId(seed);
}
