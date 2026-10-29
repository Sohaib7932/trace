"use client";

import { useEffect, useRef, useState } from "react";
import type { LensTarget } from "./code-lens";

/**
 * Phone-width caption for a magnified <CodeWindow>: a bar under the code, so the label
 * never covers the highlighted line. Server-rendered with the first target (no layout
 * shift, correct with reduced motion); follows the lens via "lens:target" events.
 */
export function LensCaption({ targets }: { targets: LensTarget[] }) {
  const ref = useRef<HTMLParagraphElement>(null);
  const [index, setIndex] = useState(0);

  useEffect(() => {
    const figure = ref.current?.closest("figure");
    if (!figure) return;
    const onTarget = (event: Event) => setIndex((event as CustomEvent<number>).detail);
    figure.addEventListener("lens:target", onTarget);
    return () => figure.removeEventListener("lens:target", onTarget);
  }, []);

  const target = targets[index] ?? targets[0];
  return (
    <p
      ref={ref}
      aria-hidden="true"
      className="flex items-center gap-2 border-t border-border bg-surface px-3.5 py-2 text-[0.75rem] md:hidden"
    >
      <span className="font-mono text-tertiary">Line {target.line}</span>
      <span className="size-1 rounded-full bg-primary" />
      <span className="font-medium text-foreground">{target.label}</span>
    </p>
  );
}
