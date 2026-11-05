import type { CSSProperties, ReactNode } from "react";

/**
 * A one-time entrance for content that appears after data loads. It is plain CSS (see `.pj-enter`), so it
 * works for elements added after the page loaded; the scroll-reveal runtime only sees elements present at load.
 * Content is visible by default; the fade only plays when motion is allowed.
 */
export function Enter({ delay = 0, className = "", children }: { delay?: number; className?: string; children: ReactNode }) {
  return <div className={`pj-enter ${className}`} style={{ "--d": `${delay}ms` } as CSSProperties}>{children}</div>;
}
