"use client";

import { useEffect, useState } from "react";
import { browserAuth } from "@/lib/supabase/browser";
import { useAuth } from "@/lib/supabase/use-auth";
import { isAvatarId, normalizeAvatarId } from "./avatars";

/**
 * What the UI shows about the signed-in person: a chosen avatar (allowlisted) and a display name
 * from their sign-in provider. Never the email as a name, never a provider photo.
 */
export type Profile = { userId: string; avatarId: string | null; displayName: string };
export const FALLBACK_NAME = "Trace learner";

const LOCAL = (userId: string) => `trace.avatar.${userId}`;
const listeners = new Set<() => void>();
const cache = new Map<string, Profile>();

/** Provider profile name (trimmed, bounded), or "Trace learner". The email is never used. */
export function displayNameFrom(metadata: Record<string, unknown> | null | undefined): string {
  for (const key of ["full_name", "name"]) {
    const value = metadata?.[key];
    if (typeof value === "string" && value.trim() && !value.includes("@")) return value.trim().slice(0, 80);
  }
  return FALLBACK_NAME;
}

/** This device's copy: { id, onlyHere } where onlyHere means saving to the account failed. */
function localAvatar(userId: string): { id: string; onlyHere: boolean } | null {
  try {
    const value = JSON.parse(localStorage.getItem(LOCAL(userId)) ?? "null") as { id?: unknown; onlyHere?: unknown } | null;
    const id = value ? normalizeAvatarId(value.id) : null;
    return id ? { id, onlyHere: value?.onlyHere === true } : null;
  } catch { return null; }
}

async function loadProfile(userId: string): Promise<Profile> {
  const auth = browserAuth();
  // getSession reads the local session (no network call) for the current user's metadata.
  const session = auth ? (await auth.auth.getSession()).data.session : null;
  const metadata = (session?.user?.id === userId ? session.user.user_metadata : null) as Record<string, unknown> | null;
  const chosen = metadata?.avatar_id;
  const local = localAvatar(userId);
  const avatarId = local?.onlyHere ? local.id : normalizeAvatarId(chosen) ?? local?.id ?? null;
  return { userId, avatarId, displayName: displayNameFrom(metadata) };
}

export function useProfile(): { status: "loading" | "guest" | "ready"; profile: Profile | null } {
  const auth = useAuth();
  const userId = auth.status === "signed-in" ? auth.userId ?? null : null;
  const [profile, setProfile] = useState<Profile | null>(null);
  const [version, setVersion] = useState(0);
  useEffect(() => {
    const notify = () => setVersion((value) => value + 1);
    listeners.add(notify);
    return () => { listeners.delete(notify); };
  }, []);
  useEffect(() => {
    if (!userId) return;
    let active = true;
    const cached = cache.get(userId);
    const load = cached ? Promise.resolve(cached) : loadProfile(userId);
    void load.then((value) => { cache.set(userId, value); if (active) setProfile(value); }).catch(() => { if (active) setProfile({ userId, avatarId: localAvatar(userId)?.id ?? null, displayName: FALLBACK_NAME }); });
    return () => { active = false; };
  }, [userId, version]);
  if (auth.status === "loading" || (userId && profile?.userId !== userId)) return { status: "loading", profile: null };
  if (!userId) return { status: "guest", profile: null };
  return { status: "ready", profile };
}

/**
 * Saves the choice to the account (Supabase user metadata) through the existing SDK. If that
 * fails, keeps it on this device only. Ids outside the allowlist are refused.
 */
export async function saveAvatar(userId: string, avatarId: string): Promise<"account" | "device"> {
  if (!isAvatarId(avatarId)) throw new Error("Choose one of Trace's avatars.");
  let where: "account" | "device" = "device";
  try {
    const auth = browserAuth();
    if (auth) {
      const { error } = await auth.auth.updateUser({ data: { avatar_id: avatarId } });
      if (!error) where = "account";
    }
  } catch { /* fall back to this device */ }
  try { localStorage.setItem(LOCAL(userId), JSON.stringify({ id: avatarId, onlyHere: where === "device" })); } catch { /* storage blocked */ }
  const previous = cache.get(userId);
  cache.set(userId, { userId, avatarId, displayName: previous?.displayName ?? FALLBACK_NAME });
  listeners.forEach((notify) => notify());
  return where;
}

/** Forget cached profiles (on sign-out, and between tests). */
export function clearProfileCache() {
  cache.clear();
  listeners.forEach((notify) => notify());
}
