"use client";

import { useEffect, useRef, useState, type CSSProperties, type ElementType, type ReactNode } from "react";

/** Sets `data-in` once the element is on screen. CSS does the rest (and shows final states without motion). */
export function InView({ as: Tag = "div", className = "", style, threshold = 0.25, children }: {
  as?: ElementType;
  className?: string;
  style?: CSSProperties;
  threshold?: number;
  children: ReactNode;
}) {
  const node = useRef<HTMLElement>(null);
  useEffect(() => {
    const element = node.current;
    if (!element) return;
    if (typeof IntersectionObserver === "undefined") { element.setAttribute("data-in", ""); return; }
    const observer = new IntersectionObserver(([entry]) => {
      if (!entry.isIntersecting) return;
      element.setAttribute("data-in", "");
      observer.disconnect();
    }, { threshold });
    observer.observe(element);
    return () => observer.disconnect();
  }, [threshold]);
  return <Tag ref={node} className={className} style={style}>{children}</Tag>;
}

/** Renders children only after the element has been seen (so a count-up starts when it is visible). */
export function WhenInView({ placeholder, children }: { placeholder: ReactNode; children: ReactNode }) {
  const node = useRef<HTMLSpanElement>(null);
  const [seen, setSeen] = useState(false);
  useEffect(() => {
    const element = node.current;
    if (!element || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(([entry]) => { if (entry.isIntersecting) { setSeen(true); observer.disconnect(); } }, { threshold: 0.4 });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return <span ref={node}>{seen ? children : placeholder}</span>;
}
