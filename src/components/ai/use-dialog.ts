"use client";

import { useEffect, useRef } from "react";

const FOCUSABLE = 'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Dialog behaviour for the help chat and tutor drawer: moves focus in when opened, keeps
 * Tab inside, closes on Escape, and returns focus to the element that opened it.
 */
export function useDialog(open: boolean, onClose: () => void, initialFocus?: () => HTMLElement | null) {
  const panel = useRef<HTMLDivElement>(null);
  const returnTo = useRef<HTMLElement | null>(null);
  const close = useRef(onClose);
  useEffect(() => { close.current = onClose; });

  useEffect(() => {
    if (!open) return;
    returnTo.current = document.activeElement as HTMLElement | null;
    const frame = requestAnimationFrame(() => (initialFocus?.() ?? panel.current?.querySelector<HTMLElement>(FOCUSABLE))?.focus());
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") { event.preventDefault(); close.current(); return; }
      if (event.key !== "Tab" || !panel.current) return;
      const items = [...panel.current.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((el) => el.offsetParent !== null);
      if (!items.length) return;
      const first = items[0], last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
    document.addEventListener("keydown", onKey);
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener("keydown", onKey);
      returnTo.current?.focus?.();
    };
    // initialFocus is read once per open.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  return panel;
}

/** Text that looks like a password or secret key must not be sent to any assistant. */
export const looksSecret = (text: string) =>
  /(password\s*[:=]|passwd|sk-[a-z0-9]{8,}|sb_secret_|sb_publishable_|eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{5,}|-----BEGIN [A-Z ]*PRIVATE KEY|api[_-]?key\s*[:=])/i.test(text);
