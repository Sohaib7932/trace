"use client";

import { useEffect } from "react";

/** Marks the site header as scrolled past 40px, for a slightly deeper nav shadow. */
export function NavScroll() {
  useEffect(() => {
    const header = document.getElementById("site-header");
    if (!header) return;
    let frame = 0;
    const update = () => {
      frame = 0;
      header.toggleAttribute("data-scrolled", window.scrollY > 40);
    };
    const onScroll = () => {
      if (!frame) frame = requestAnimationFrame(update);
    };
    update();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      window.removeEventListener("scroll", onScroll);
      cancelAnimationFrame(frame);
    };
  }, []);
  return null;
}
