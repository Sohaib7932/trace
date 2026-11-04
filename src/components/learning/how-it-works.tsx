"use client";

import { CircleHelp, X } from "lucide-react";
import { useState } from "react";
import { createPortal } from "react-dom";
import { useDialog } from "@/components/ai/use-dialog";
import { VERIFICATION_MODES, verificationCopy } from "@/lib/learning/verification";
import { VerificationBadge } from "./verification-badge";

/** A short explanation of the two kinds of lessons and how each is checked. */
export function HowItWorks({ className = "" }: { className?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" aria-haspopup="dialog" onClick={() => setOpen(true)} className={`inline-flex min-h-11 items-center gap-2 font-medium underline underline-offset-4 ${className}`}>
        <CircleHelp aria-hidden="true" className="size-4" strokeWidth={1.8} />How it works
      </button>
      {/* Portal: an animated (transformed) ancestor would otherwise trap position: fixed. */}
      {open && createPortal(<HowItWorksDialog onClose={() => setOpen(false)} />, document.body)}
    </>
  );
}

function HowItWorksDialog({ onClose }: { onClose: () => void }) {
  const panel = useDialog(true, onClose);
  return (
    <>
      <div aria-hidden="true" className="tutor-scrim" onClick={onClose} />
      <div ref={panel} role="dialog" aria-modal="true" aria-labelledby="how-title" className="how-dialog">
        <button type="button" onClick={onClose} aria-label="Close" className="absolute top-3 right-3 inline-flex size-11 items-center justify-center rounded-lg text-secondary hover:bg-foreground/5">
          <X aria-hidden="true" className="size-5" strokeWidth={2} />
        </button>
        <h2 id="how-title" className="type-h3 pr-12">How Trace lessons work</h2>
        <ol className="mt-5 grid gap-4 text-[0.9375rem] leading-relaxed">
          <li><span className="font-semibold">1. Read real code.</span> <span className="text-secondary">Each lesson starts with a short piece of code, like code your AI agent might write.</span></li>
          <li><span className="font-semibold">2. Predict, then change one thing.</span> <span className="text-secondary">You commit to what you think will happen before you see the result.</span></li>
          <li><span className="font-semibold">3. See what really happened.</span> <span className="text-secondary">Then practise the same idea again later, with less help.</span></li>
        </ol>
        <h3 className="mt-6 text-[1rem] font-semibold">Two kinds of lessons</h3>
        <ul className="mt-2 grid gap-2 text-[0.9375rem] leading-relaxed">
          <li><span className="font-medium">Trace lessons</span> <span className="text-secondary">are written by the Trace team and checked on a real server.</span></li>
          <li><span className="font-medium">Lessons you create</span> <span className="text-secondary">are drafted by AI from your request and marked &ldquo;AI-generated&rdquo;. AI drafts and explains; it never decides whether you&apos;re right.</span></li>
        </ul>
        <h3 className="mt-6 text-[1rem] font-semibold">How answers are checked</h3>
        <ul className="mt-3 grid gap-3">
          {VERIFICATION_MODES.map((mode) => (
            <li key={mode}><VerificationBadge mode={mode} /><p className="mt-1 text-[0.875rem] text-secondary">{verificationCopy[mode].detail}</p></li>
          ))}
        </ul>
        <button type="button" onClick={onClose} className="mt-6 inline-flex min-h-11 items-center rounded-[11px] bg-foreground px-5 font-medium text-white hover:bg-foreground/85">Got it</button>
      </div>
    </>
  );
}
