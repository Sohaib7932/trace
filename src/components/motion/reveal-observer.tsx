"use client";

import { useEffect } from "react";

/**
 * Reveals every [data-reveal] element as it scrolls into view by setting
 * data-revealed. All styling lives in globals.css, and only applies under
 * html.js with motion allowed, so content is never hidden without JS.
 */
export function RevealObserver() {
  useEffect(() => {
    const targets = document.querySelectorAll<HTMLElement>("[data-reveal]:not([data-revealed])");
    if (!("IntersectionObserver" in window)) {
      targets.forEach((element) => element.setAttribute("data-revealed", ""));
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            entry.target.setAttribute("data-revealed", "");
            observer.unobserve(entry.target);
          }
        }
      },
      { rootMargin: "0px 0px -10% 0px", threshold: 0.12 },
    );
    targets.forEach((element) => observer.observe(element));
    return () => observer.disconnect();
  }, []);

  return null;
}
