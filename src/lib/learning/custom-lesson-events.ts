"use client";

import { useEffect, useRef } from "react";
import { refreshNavSignals } from "./nav-signals";

/** One query key for the learner's custom lessons, shared by My lessons, /learn and /account. */
export const customLessonKeys = {
  all: ["custom-lessons"] as const,
  list: (userId: string | null | undefined) => ["custom-lessons", userId ?? null] as const,
};

const EVENT = "trace:custom-lessons-changed";
const CHANNEL = "trace-custom-lessons";
// Every tab has its own id, so a tab ignores its own broadcast and only reacts to other tabs.
const TAB = typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID() : String(Math.random());

/**
 * Call after a custom lesson is created, answered (progress) or deleted. Every view that lists
 * custom lessons refetches, in this tab and in other open tabs, and the navbar count updates.
 */
export function notifyCustomLessonsChanged() {
  refreshNavSignals();
  window.dispatchEvent(new Event(EVENT));
  try { const channel = new BroadcastChannel(CHANNEL); channel.postMessage(TAB); channel.close(); } catch { /* no BroadcastChannel: this tab only */ }
}

export function useCustomLessonsChanged(onChange: () => void) {
  const callback = useRef(onChange);
  useEffect(() => { callback.current = onChange; });
  useEffect(() => {
    const notify = () => callback.current();
    window.addEventListener(EVENT, notify);
    let channel: BroadcastChannel | null = null;
    try { channel = new BroadcastChannel(CHANNEL); channel.onmessage = (message: MessageEvent) => { if (message.data !== TAB) notify(); }; } catch { /* no BroadcastChannel */ }
    return () => { window.removeEventListener(EVENT, notify); channel?.close(); };
  }, []);
}
