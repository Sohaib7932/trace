"use client";

import { useEffect, useRef } from "react";

/**
 * "Follow the signal": one trace line travels from Your code, through Trace, to Lessons. Original SVG.
 * The travelling dot only runs while the drawing is on screen; with reduced motion nothing moves and
 * the line is drawn in full.
 */
export function TraceFlow({ className = "" }: { className?: string }) {
  const node = useRef<SVGSVGElement>(null);
  useEffect(() => {
    const element = node.current;
    if (!element || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(([entry]) => element.toggleAttribute("data-live", entry.isIntersecting), { threshold: 0.2 });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return (
    <svg ref={node} role="img" aria-label="Your code goes through Trace and comes out as lessons" viewBox="0 0 760 190" className={`pj-flow ${className}`} fill="none">
      <path className="pj-flow-rail" d="M96 96 C 190 96 200 54 300 54 S 430 138 520 138 S 610 96 664 96" />
      <path className="pj-flow-line" pathLength={1} d="M96 96 C 190 96 200 54 300 54 S 430 138 520 138 S 610 96 664 96" />
      <circle className="pj-flow-dot" r="7" />

      <g transform="translate(24 54)">
        <rect width="144" height="84" rx="14" className="pj-flow-box" />
        <path d="M20 26h52M32 42h76M32 58h44" className="pj-flow-code" />
        <text x="72" y="108" textAnchor="middle" className="pj-flow-label">Your code</text>
      </g>
      <g transform="translate(258 12)">
        <rect width="84" height="84" rx="42" className="pj-flow-box pj-flow-hub" />
        {/* The Trace mark: a signal from an input node to a lit outcome node. */}
        <g transform="translate(15.6 15.6) scale(2.2)" fill="none" stroke="var(--foreground)" strokeWidth="1.6" strokeLinecap="round">
          <circle cx="5" cy="6" r="2.25" />
          <path d="M7.2 6.6h3.3c1.7 0 2.5.9 2.5 2.6v5.6c0 1.7.8 2.6 2.5 2.6h1.3" />
          <circle cx="19" cy="17.4" r="2.6" fill="var(--primary)" stroke="none" />
        </g>
        <text x="42" y="112" textAnchor="middle" className="pj-flow-label">Trace</text>
      </g>
      <g transform="translate(592 54)">
        <rect width="144" height="84" rx="14" className="pj-flow-box" />
        <rect x="18" y="20" width="108" height="14" rx="7" className="pj-flow-step" />
        <rect x="18" y="42" width="84" height="14" rx="7" className="pj-flow-step pj-flow-step-2" />
        <rect x="18" y="64" width="60" height="10" rx="5" className="pj-flow-step pj-flow-step-3" />
        <text x="72" y="108" textAnchor="middle" className="pj-flow-label">Lessons</text>
      </g>
    </svg>
  );
}
