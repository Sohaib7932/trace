import Link from "next/link";
import { ArrowRight, Lock } from "lucide-react";

/**
 * Real lessons are for signed-in learners. Guests get the interactive demo on the homepage
 * (sample results, clearly labelled) instead of a real session. This is a product rule in
 * the UI; it makes no learner, session or journey request.
 */
export function SignInRequired({ next, title = "Sign in to start this lesson", unconfigured = false }: { next: string; title?: string; unconfigured?: boolean }) {
  const query = `?next=${encodeURIComponent(next)}`;
  return (
    <section aria-labelledby="sign-in-required-title" className="hub-card mt-6 max-w-[44rem] p-6 sm:p-8">
      <p className="inline-flex items-center gap-2 font-mono text-[0.75rem] tracking-[0.04em] text-secondary uppercase"><Lock aria-hidden="true" className="size-3.5" strokeWidth={1.8} />Account needed</p>
      <h2 id="sign-in-required-title" className="type-h3 mt-3">{title}</h2>
      <p className="mt-3 max-w-[60ch] text-[0.9375rem] leading-relaxed text-secondary">
        Lessons run against a real server and save your predictions, attempts and results to your account.
        Without an account, you can try the interactive demo on the homepage. It uses sample results and saves nothing.
      </p>
      {unconfigured ? (
        <p role="note" className="mt-4 text-[0.9375rem] font-medium">Accounts aren&apos;t set up on this copy of Trace, so lessons can&apos;t be opened here.</p>
      ) : (
        <div className="mt-6 flex flex-wrap gap-3">
          <Link href={`/sign-in${query}`} className="inline-flex min-h-11 items-center rounded-[11px] bg-foreground px-5 font-medium text-white hover:bg-foreground/85">Sign in</Link>
          <Link href={`/sign-up${query}`} className="inline-flex min-h-11 items-center rounded-[11px] border border-border-strong bg-surface px-5 font-medium hover:bg-surface-muted">Create account</Link>
        </div>
      )}
      <Link href="/#demo" className="group mt-5 inline-flex min-h-11 items-center gap-2 font-medium underline underline-offset-4">
        Try the demo lesson<ArrowRight aria-hidden="true" className="size-4 transition-transform duration-200 group-hover:translate-x-0.5" strokeWidth={1.8} />
      </Link>
    </section>
  );
}
