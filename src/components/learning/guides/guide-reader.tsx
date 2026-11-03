"use client";

import Link from "next/link";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { learningGuidesApi } from "@/lib/api/learning-guides";
import { useAuth } from "@/lib/supabase/use-auth";
import { guideError } from "../hub/private-guide-hub";

export function GuideReader({ guideId }: { guideId: string }) {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: false } } }));
  return <QueryClientProvider client={client}><OwnedGuide guideId={guideId} /></QueryClientProvider>;
}

function OwnedGuide({ guideId }: { guideId: string }) {
  const auth = useAuth();
  const guide = useQuery({
    queryKey: ["private-guide", auth.status === "signed-in" ? auth.userId : null, guideId],
    enabled: auth.status === "signed-in",
    queryFn: ({ signal }) => learningGuidesApi.get(guideId, signal),
  });
  if (auth.status === "loading") return <p role="status" className="py-10 text-secondary">Checking your sign-in…</p>;
  if (auth.status !== "signed-in") return <section className="hub-card my-10 p-6"><h1 className="type-h3">Sign in to read your private guide</h1><p className="mt-3 text-secondary">Private guides are available only to the account that created them.</p><Link className="mt-4 inline-flex min-h-11 items-center font-medium underline" href={`/sign-in?next=${encodeURIComponent(`/learn/guides/${guideId}`)}`}>Sign in</Link></section>;
  if (guide.isPending) return <p role="status" className="py-10 text-secondary">Loading your private guide…</p>;
  if (guide.error) return <section role="alert" className="hub-card my-10 p-6"><h1 className="type-h3">The guide could not be opened</h1><p className="mt-3 text-secondary">{guideError(guide.error)}</p><button className="mt-4 min-h-11 underline" onClick={() => void guide.refetch()}>Try opening again</button></section>;
  const saved = guide.data;
  if (saved.status !== "ready" || !saved.content || saved.ungraded !== true || saved.execution_status !== "not_executed") return <section className="hub-card my-10 p-6"><h1 className="type-h3">{saved.status === "generating" ? "Your guide is still generating" : "This guide is unavailable"}</h1><p className="mt-3 whitespace-pre-wrap break-words text-secondary">Topic: {saved.topic}</p><p className="mt-3 text-secondary">{saved.status === "generating" ? "This is the saved request, not a completed guide. Refresh to check its status." : "A valid guide was not produced. No code was executed, and no lesson was completed or published."}</p>{saved.status === "generating" && <button className="mt-4 min-h-11 underline" onClick={() => void guide.refetch()}>Refresh guide status</button>}<Link className="ml-4 inline-flex min-h-11 items-center underline" href="/learn">Back to lessons</Link></section>;
  const content = saved.content;
  return <article className="mx-auto max-w-[780px] py-[clamp(32px,5vw,64px)]">
    <p className="text-[0.75rem] font-semibold tracking-wide text-secondary">PRIVATE LEARNING GUIDE · VERSION {saved.version}</p>
    <h1 className="type-h2 mt-4 break-words">{content.title}</h1>
    <p className="mt-4 whitespace-pre-wrap break-words text-[1rem] leading-relaxed text-secondary">{content.description}</p>
    <aside aria-label="Guide limitations" className="mt-6 rounded-xl border border-border bg-surface-muted p-4 text-[0.875rem] leading-relaxed"><p>AI-generated educational material. Examples have not been executed. Practice is ungraded and does not change verified lesson progress or competency scores.</p>{saved.source === "test_fixture" && <p className="mt-2 font-semibold">Test fixture content · This is not a live Gemini result.</p>}<p className="mt-2 text-secondary">Check suggestions before using them in your own project. This guide stays private to your account.</p></aside>
    <section className="mt-8" aria-labelledby="guide-objectives"><h2 id="guide-objectives" className="type-h3">What this guide covers</h2><ul className="mt-3 list-disc space-y-2 pl-5 text-[0.9375rem] leading-relaxed">{content.learning_objectives.map((objective, index) => <li className="whitespace-pre-wrap break-words" key={index}>{objective}</li>)}</ul></section>
    <ol className="mt-8 grid gap-6">{content.sections.map((section, index) => <li key={section.id} className="hub-card min-w-0 p-5 sm:p-7"><section aria-labelledby={`guide-section-${section.id}`}><p className="text-[0.75rem] font-medium text-secondary">STEP {index + 1}</p><h2 id={`guide-section-${section.id}`} className="mt-2 text-[1.25rem] font-semibold break-words">{section.title}</h2><p className="mt-3 whitespace-pre-wrap break-words text-[0.9375rem] leading-relaxed">{section.explanation}</p>
      {section.example && <figure className="mt-5 min-w-0"><figcaption className="text-[0.8125rem] font-medium text-secondary">Suggested {section.example.language} example · Not executed</figcaption><pre className="mt-2 max-w-full whitespace-pre-wrap break-words [overflow-wrap:anywhere] rounded-xl bg-surface-muted p-4 text-[0.8125rem] leading-relaxed"><code>{section.example.code}</code></pre><p className="mt-3 whitespace-pre-wrap break-words text-[0.875rem] leading-relaxed text-secondary">{section.example.explanation}</p></figure>}
      {section.practice && <div className="mt-5 rounded-xl border border-border p-4"><h3 className="text-[0.875rem] font-semibold">Try it yourself · Ungraded</h3><p className="mt-2 whitespace-pre-wrap break-words text-[0.875rem] leading-relaxed">{section.practice}</p><label className="mt-3 grid gap-2 text-[0.8125rem] text-secondary">Your private scratch notes (not saved or sent)<textarea rows={3} className="w-full rounded-lg border border-border-strong bg-surface px-3 py-2 text-foreground" placeholder="Use this space to think through the practice. There is no automatic check." /></label></div>}
      <p className="mt-4 whitespace-pre-wrap break-words text-[0.875rem] leading-relaxed"><span className="font-semibold">Learning outcome to aim for: </span>{section.expected_outcome}</p>
    </section></li>)}</ol>
    <section className="mt-8 rounded-xl bg-surface-muted p-5"><h2 className="type-h3">Review the idea</h2><p className="mt-3 whitespace-pre-wrap break-words text-[0.9375rem] leading-relaxed">{content.summary}</p></section>
    <Link href="/learn" className="mt-6 inline-flex min-h-11 items-center font-medium underline underline-offset-4">Back to your lessons</Link>
  </article>;
}
