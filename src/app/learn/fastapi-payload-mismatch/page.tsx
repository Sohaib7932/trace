import type { Metadata } from "next";
import { CompletionPanel } from "@/components/learning/completion-panel";
import { LessonTopBar } from "@/components/learning/lesson-top-bar";
import { LearningWorkspace } from "@/components/learning/workspace";

export const metadata: Metadata = { title: "Follow the note · Trace", description: "Read the payload, commit a prediction, and verify a real saved note." };

const LESSON = "fastapi-payload-mismatch";

export default function LessonPage() {
  return <main id="main" className="shell">
    <LessonTopBar title="Follow the note" />
    <LearningWorkspace lessonId={LESSON}>
      <CompletionPanel lessonId={LESSON} />
    </LearningWorkspace>
  </main>;
}
