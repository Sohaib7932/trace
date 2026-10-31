import type { Metadata } from "next";
import Link from "next/link";
import { TraceMark } from "@/components/brand/trace-mark";
import { LearningWorkspace } from "@/components/learning/workspace";
import { AccountLink } from "@/components/auth/account-link";
import { ButtonLink } from "@/components/ui/button-link";

export const metadata: Metadata = { title: "The Nested Payload Problem · Trace", description: "Transfer the receiving-contract concept to nested task JSON, then return for retrieval." };

export default function TransferPage() {
  return <main id="main" className="shell">
    <nav aria-label="Lesson navigation" className="flex items-center justify-between border-b border-border py-5">
      <Link href="/" aria-label="Trace home" className="inline-flex items-center gap-2 font-semibold"><TraceMark className="size-8" />trace</Link>
      <div className="flex items-center gap-1"><AccountLink guestLabel="Save progress" /><ButtonLink href="/learn/fastapi-payload-mismatch" variant="ghost" size="sm">Original lesson</ButtonLink></div>
    </nav>
    <LearningWorkspace lessonId="fastapi-nested-payload-transfer" />
  </main>;
}
