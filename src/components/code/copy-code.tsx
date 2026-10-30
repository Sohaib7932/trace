"use client";

import { Check, Copy } from "lucide-react";
import { useEffect, useState } from "react";

/** Copy-to-clipboard for a code window, inside its title bar. Hidden without JS. */
export function CopyCode({ text, dark = false }: { text: string; dark?: boolean }) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 1600);
    return () => clearTimeout(timer);
  }, [copied]);

  return (
    <button
      type="button"
      onClick={() => navigator.clipboard?.writeText(text).then(() => setCopied(true), () => undefined)}
      className={`copy-code size-7 shrink-0 items-center justify-center rounded-[7px] transition-colors duration-[180ms] ${
        dark ? "text-editor-muted hover:bg-white/10 hover:text-editor-foreground" : "text-secondary hover:bg-surface-muted hover:text-foreground"
      }`}
    >
      {copied ? <Check aria-hidden="true" className="size-3.5" strokeWidth={2.2} /> : <Copy aria-hidden="true" className="size-3.5" strokeWidth={1.8} />}
      <span className="sr-only">{copied ? "Copied" : "Copy code"}</span>
      <span aria-live="polite" className="sr-only">{copied ? "Code copied to clipboard" : ""}</span>
    </button>
  );
}
