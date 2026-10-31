import Link from "next/link";
import { Wordmark } from "@/components/brand/trace-mark";

export function AuthShell({ children, wide = false }: { children: React.ReactNode; wide?: boolean }) {
  return <main id="main" className="shell min-h-screen py-8 sm:py-12">
    <nav aria-label="Account navigation" className="mb-10 flex items-center justify-between gap-3">
      <Link href="/" aria-label="Trace home"><Wordmark /></Link>
      <Link href="/learn/fastapi-payload-mismatch" className="text-sm text-secondary underline underline-offset-4">Keep learning</Link>
    </nav>
    <div className={`mx-auto rounded-2xl border border-border bg-surface p-6 shadow-[var(--shadow-float)] sm:p-10 ${wide ? "max-w-2xl" : "max-w-md"}`}>{children}</div>
  </main>;
}

export const authInput = "mt-2 min-h-12 w-full rounded-xl border border-border bg-background px-4 text-foreground";
export const authButton = "inline-flex min-h-12 w-full items-center justify-center rounded-xl bg-foreground px-5 font-medium text-background disabled:cursor-wait disabled:opacity-50";
