/**
 * Lazy GSAP + ScrollTrigger. Only client effects call this, through a dynamic import,
 * so GSAP is never part of the first-load bundle. Loaded once, shared by every caller.
 */
import type { gsap as GsapType } from "gsap";
import type { ScrollTrigger as ScrollTriggerType } from "gsap/ScrollTrigger";

export type Gsap = { gsap: typeof GsapType; ScrollTrigger: typeof ScrollTriggerType };

let loading: Promise<Gsap> | null = null;

export function loadGsap(): Promise<Gsap> {
  loading ??= Promise.all([import("gsap"), import("gsap/ScrollTrigger")]).then(([core, plugin]) => {
    const { gsap } = core;
    const { ScrollTrigger } = plugin;
    gsap.registerPlugin(ScrollTrigger);
    // Pinned sections measure layout; re-measure once web fonts have settled.
    document.fonts.ready.then(() => ScrollTrigger.refresh());
    return { gsap, ScrollTrigger };
  });
  return loading;
}

/** If GSAP can't load, drop the pre-applied "from" states so the static layout shows. */
export function markMotionFallback() {
  document.documentElement.classList.add("motion-fallback");
}
