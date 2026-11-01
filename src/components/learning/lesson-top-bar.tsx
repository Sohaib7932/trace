import Link from "next/link";
import { ChevronRight } from "lucide-react";
import { Wordmark } from "@/components/brand/trace-mark";
import { AccountLink } from "@/components/auth/account-link";

/** Quiet top bar for lesson pages: home, a breadcrumb back to the lessons hub, account. */
export function LessonTopBar({ title }: { title: string }) {
  return (
    <header className="flex items-center justify-between gap-4 border-b border-border py-4">
      <div className="flex min-w-0 items-center gap-4 sm:gap-6">
        <Link href="/" aria-label="Trace home" className="shrink-0 rounded-md"><Wordmark /></Link>
        <nav aria-label="Breadcrumb" className="min-w-0">
          <ol className="flex min-w-0 items-center gap-1.5 text-[0.875rem]">
            <li><Link href="/learn" className="inline-flex min-h-11 items-center rounded-md font-medium text-secondary hover:text-foreground">Lessons</Link></li>
            <li aria-hidden="true"><ChevronRight className="size-3.5 text-tertiary" strokeWidth={2} /></li>
            <li className="min-w-0 truncate font-medium text-foreground" aria-current="page">{title}</li>
          </ol>
        </nav>
      </div>
      <AccountLink guestLabel="Save progress" />
    </header>
  );
}
