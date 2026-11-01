/**
 * Every link points somewhere real. Section links include the "/" path so they also
 * work from other pages (on the homepage they only scroll).
 */
export const navLinks = [
  { href: "/#features", label: "Product" },
  { href: "/#how-it-works", label: "How it works" },
  { href: "/#progress", label: "Learning approach" },
  { href: "/learn", label: "Lessons" },
] as const;

export const primaryCta = { href: "/learn", label: "Try Trace" } as const;
