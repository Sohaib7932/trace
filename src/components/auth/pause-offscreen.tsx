"use client";

import { useEffect, useRef } from "react";

/** Pauses its parent's CSS animations while the parent is off-screen. */
export function PauseOffscreen() {
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    const host = ref.current?.parentElement;
    if (!host) return;
    const observer = new IntersectionObserver(([entry]) => host.toggleAttribute("data-paused", !entry.isIntersecting));
    observer.observe(host);
    return () => observer.disconnect();
  }, []);
  return <span ref={ref} hidden />;
}
