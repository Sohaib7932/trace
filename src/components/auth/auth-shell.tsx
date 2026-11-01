import Link from "next/link";
import { Wordmark } from "@/components/brand/trace-mark";
import { AuthArt } from "./auth-art";

/** Split layout for sign-in, sign-up and password pages: form at left, original art at right (desktop). */
export function AuthShell({ children }: { children: React.ReactNode }) {
  return (
    <main id="main" className="grid min-h-[calc(100dvh-2*var(--frame))] lg:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)]">
      <div className="flex flex-col px-[var(--gutter)] py-6 sm:py-8 lg:px-[clamp(40px,5vw,88px)]">
        <nav aria-label="Account navigation" className="flex items-center justify-between gap-3">
          <Link href="/" aria-label="Trace home" className="rounded-md"><Wordmark /></Link>
          <Link href="/learn" className="inline-flex min-h-11 items-center text-[0.875rem] font-medium text-secondary underline-offset-4 hover:text-foreground hover:underline">Keep learning</Link>
        </nav>
        <div className="mx-auto flex w-full max-w-[25rem] flex-1 flex-col justify-center py-10 sm:py-14">{children}</div>
      </div>
      <div className="hidden p-3 lg:block lg:p-4">
        <div className="sticky top-4 h-[calc(100dvh-2*var(--frame)-2rem)] min-h-[560px]"><AuthArt /></div>
      </div>
    </main>
  );
}

export const authInput = "auth-input mt-2 min-h-12 w-full rounded-xl border border-border-strong bg-surface px-4 text-[1rem] text-foreground transition-[border-color,box-shadow] duration-[180ms] placeholder:text-tertiary";
export const authButton = "inline-flex min-h-12 w-full items-center justify-center gap-2 rounded-xl bg-foreground px-5 font-medium text-white transition-[background-color,translate] duration-[180ms] hover:bg-foreground/85 active:translate-y-px disabled:cursor-not-allowed disabled:opacity-50";
