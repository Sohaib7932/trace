"use client";

import { useEffect, useState } from "react";
import { accountApi, customLessonsApi, learningApi } from "@/lib/api/client";
import { useAuth } from "@/lib/supabase/use-auth";

/** Small facts the navbar shows for a signed-in learner. Never shown for guests. */
export type NavSignals = { myLessons: number | null; followUpDue: boolean };

const EMPTY: NavSignals = { myLessons: null, followUpDue: false };
const TTL_MS = 30_000;

// One read per account, shared by every navbar control and reused for a short time.
let cache: { user: string; at: number; value: Promise<NavSignals> } | null = null;
const listeners = new Set<() => void>();

async function load(): Promise<NavSignals> {
  const [list, me] = await Promise.all([customLessonsApi.list().catch(() => null), accountApi.me().catch(() => null)]);
  // backend: reading the journey without a learner would create one (and end any guest-history
  // claim), so it is only read for an account that already has a learner.
  let followUpDue = false;
  if (me?.learner_id) {
    const journey = await learningApi.journey().catch(() => null);
    followUpDue = Boolean(journey?.checkpoints.some((checkpoint) => checkpoint.status === "due"));
  }
  return { myLessons: list ? list.items.length : null, followUpDue };
}

/** Call after a lesson is created or deleted so the navbar count is read again. */
export function refreshNavSignals() {
  cache = null;
  listeners.forEach((notify) => notify());
}

export function useNavSignals(): NavSignals {
  const auth = useAuth();
  const user = auth.status === "signed-in" ? auth.userId ?? auth.email ?? "signed-in" : null;
  const [state, setState] = useState<{ user: string; value: NavSignals } | null>(null);
  const [version, setVersion] = useState(0);
  useEffect(() => {
    const notify = () => setVersion((value) => value + 1);
    listeners.add(notify);
    return () => { listeners.delete(notify); };
  }, []);
  useEffect(() => {
    if (!user) return;
    if (!cache || cache.user !== user || Date.now() - cache.at > TTL_MS) cache = { user, at: Date.now(), value: load() };
    let active = true;
    void cache.value.then((value) => { if (active) setState({ user, value }); });
    return () => { active = false; };
  }, [user, version]);
  return user && state?.user === user ? state.value : EMPTY;
}
