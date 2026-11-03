import type { Metadata } from "next";
import { Suspense } from "react";
import { SiteHeader } from "@/components/layout/site-header";
import { createCta } from "@/components/layout/nav-links";
import { CustomLessonView } from "@/components/learning/custom/custom-lesson-view";

// Private lessons: never indexed, and the title is generic (no learner content in metadata).
export const metadata: Metadata = { title: "Your lesson · Trace", robots: { index: false } };

async function View({ params }: { params: Promise<{ lessonId: string }> }) {
  const { lessonId } = await params;
  return <CustomLessonView lessonId={lessonId} />;
}

export default function CustomLessonPage({ params }: { params: Promise<{ lessonId: string }> }) {
  return (
    <>
      <SiteHeader cta={createCta} />
      <main id="main" className="shell">
        <Suspense fallback={<p role="status" className="py-12 text-secondary">Loading your lesson…</p>}>
          <View params={params} />
        </Suspense>
      </main>
    </>
  );
}
