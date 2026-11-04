"use client";

import Link from "next/link";
import { ArrowRight, Sparkles } from "lucide-react";
import { useEffect, useState, type CSSProperties } from "react";
import { customLessonsApi, type CustomLessonSummary } from "@/lib/api/client";
import { examplePrompts } from "@/lib/learning/composer";
import { useAuth } from "@/lib/supabase/use-auth";

const shortExamples = [
  { label: "FastAPI request checks", prompt: examplePrompts[0] },
  { label: "Express double response", prompt: examplePrompts[1] },
  { label: "SQL duplicate rows", prompt: examplePrompts[2] },
] as const;

/**
 * "My lessons": lessons the learner created (AI-generated, labelled as such), loaded from the
 * real API for signed-in learners, plus the way in: one button to the composer.
 */
export function MyLessons() {
  const auth = useAuth();
  const identity = auth.status === "signed-in" ? auth.userId : auth.status;
  return <AccountLessons key={identity} />;
}

function AccountLessons() {
  const auth = useAuth();
  const [items, setItems] = useState<CustomLessonSummary[] | null>(null);
  const [failed, setFailed] = useState(false);
  const signedIn = auth.status === "signed-in";
  useEffect(() => {
    if (!signedIn) return;
    let active = true;
    customLessonsApi.list()
      .then((list) => { if (active) setItems(list.items); })
      .catch(() => { if (active) setFailed(true); });
    return () => { active = false; };
  }, [signedIn]);
  const empty = !signedIn || (items !== null && items.length === 0);
  return (
    <section aria-labelledby="my-lessons-title" className="mt-[clamp(48px,6vw,80px)]">
      <h2 id="my-lessons-title" className="type-h3">My lessons</h2>
      <p className="mt-2 max-w-[62ch] text-[0.9375rem] leading-relaxed text-secondary">Lessons you create are drafted by AI from your request and marked &ldquo;AI-generated&rdquo;, so you can tell them apart from Trace lessons. They&apos;re private to your account.</p>
      {signedIn && items === null && !failed && <p role="status" className="mt-5 text-[0.875rem] text-secondary">Loading your lessons…</p>}
      {failed && <p role="alert" className="mt-5 text-[0.875rem] text-secondary">Your lessons couldn&apos;t load right now. Refresh to try again.</p>}
      {items && items.length > 0 && (
        <ul className="mt-5 grid gap-3 md:grid-cols-2">
          {items.map((lesson) => (
            <li key={lesson.id}>
              <Link href={`/learn/custom/${lesson.id}`} className="my-lesson-card group">
                <span className="flex flex-wrap items-center gap-1.5 text-[0.75rem]">
                  <span className="rounded-full bg-primary-soft px-2 py-0.5 font-medium text-primary-ink">AI-generated</span>
                  <span className="rounded-full border border-border px-2 py-0.5">{lesson.language}</span>
                  <span className="rounded-full border border-border px-2 py-0.5 capitalize">{lesson.level}</span>
                </span>
                <span className="mt-2 block text-[1.0625rem] font-semibold tracking-[-0.01em] group-hover:underline">{lesson.title}</span>
                <span className="mt-1 block text-[0.875rem] text-secondary">{lesson.completed_challenges === lesson.challenge_count ? "Done" : lesson.completed_challenges > 0 ? "In progress" : "Not started"} · {lesson.completed_challenges} of {lesson.challenge_count} challenges · Answers checked against an answer key</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      <div className="create-card mt-5 grid gap-6 p-5 sm:p-7 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
        <div>
          <p className="inline-flex items-center gap-2 text-[0.75rem] font-semibold tracking-[0.06em] text-primary-ink uppercase"><Sparkles aria-hidden="true" className="size-3.5" strokeWidth={2} />Create your own</p>
          <p className="mt-2 text-[1.125rem] font-semibold tracking-[-0.01em]">{empty ? "You haven't created a lesson yet." : "Want another lesson?"}</p>
          <p className="mt-1 max-w-[56ch] text-[0.9375rem] leading-relaxed text-secondary">Describe what you want to understand, in any language. Trace drafts a short lesson in a minute or so.</p>
          <p className="mt-4 text-[0.8125rem] font-medium text-secondary">For example</p>
          <ul className="mt-2 flex flex-wrap gap-2">
            {shortExamples.map((example) => (
              <li key={example.label}><Link href={`/learn/new?prompt=${encodeURIComponent(example.prompt)}`} className="composer-chip">{example.label}</Link></li>
            ))}
          </ul>
        </div>
        <Link href="/learn/new" className="group inline-flex min-h-11 items-center gap-2 self-start rounded-[11px] border border-border-strong bg-surface px-5 font-medium transition-colors hover:bg-surface-muted lg:self-center">
          Create a lesson<ArrowRight aria-hidden="true" className="size-4 transition-transform duration-200 group-hover:translate-x-0.5" strokeWidth={1.8} />
        </Link>
      </div>
    </section>
  );
}

/** First-run guide. Shown until the learner has started any lesson. */
export function StartHere({ firstLessonHref }: { firstLessonHref: string }) {
  // Link names differ from the hub's "Start lesson 1" button so each control has its own name.
  const steps = [
    { title: "Try a Trace lesson", body: "Read real code, predict what the server does, then change one thing.", href: firstLessonHref, action: "Open lesson 1" },
    { title: "Create your own", body: "Describe a topic or bug you care about, in any language.", href: "/learn/new", action: "Open the composer" },
    { title: "Practise again later", body: "Follow-ups bring the same idea back in new code, with less help.", href: "#follow-ups", action: "See follow-ups" },
  ];
  return (
    <section aria-labelledby="start-title" className="hub-enter mt-6 rounded-2xl bg-surface-muted p-5 sm:p-6" style={{ "--d": "80ms" } as CSSProperties}>
      <h2 id="start-title" className="text-[1rem] font-semibold">Start here</h2>
      <ol className="start-steps mt-4 grid gap-4 md:grid-cols-3">
        {steps.map((step, index) => (
          <li key={step.title} className="start-step">
            <span aria-hidden="true" className="start-num">{index + 1}</span>
            <p className="font-semibold">{step.title}</p>
            <p className="mt-1 text-[0.875rem] leading-relaxed text-secondary">{step.body}</p>
            <Link href={step.href} className="mt-2 inline-flex min-h-11 items-center gap-1.5 text-[0.875rem] font-medium underline underline-offset-4">{step.action}</Link>
          </li>
        ))}
      </ol>
    </section>
  );
}

// Private guides remain a separate, ungraded learning format.
export { YourLessons, CreateCustomLesson } from "./private-guide-hub";
