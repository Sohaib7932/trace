import type { Metadata } from "next";
import { CompletionPanel } from "@/components/learning/completion-panel";
import { AmbientPage } from "@/components/layout/ambient-page";
import { SiteHeader } from "@/components/layout/site-header";
import { createCta } from "@/components/layout/nav-links";
import { LearningWorkspace } from "@/components/learning/workspace";

export const metadata: Metadata = { title: "Follow the note · Trace", description: "Read the payload, commit a prediction, and verify a real saved note." };

const LESSON = "fastapi-payload-mismatch";

export default function LessonPage() {
  return (
    <AmbientPage calm>
      <SiteHeader cta={createCta} />
      <main id="main" className="shell">
        <LearningWorkspace lessonId={LESSON}>
          <CompletionPanel lessonId={LESSON} />
        </LearningWorkspace>
      </main>
    </AmbientPage>
  );
}
