import type { Metadata } from "next";
import Link from "next/link";
import { TraceMark } from "@/components/brand/trace-mark";
import { LearningWorkspace } from "@/components/learning/workspace";
import { ButtonLink } from "@/components/ui/button-link";

export const metadata: Metadata = { title: "Follow the note · Trace", description: "Read the payload, commit a prediction, and verify a real saved note." };

export default function LessonPage() {
  return <main id="main" className="shell">
    <nav aria-label="Lesson navigation" className="flex items-center justify-between border-b border-border py-5">
      <Link href="/" aria-label="Trace home" className="inline-flex items-center gap-2 font-semibold"><TraceMark className="size-8" />trace</Link>
      <ButtonLink href="/" variant="ghost" size="sm">Back to Trace</ButtonLink>
    </nav>
    <LearningWorkspace />
  </main>;
}
