import type { Metadata } from "next";
import { CompletionPanel } from "@/components/learning/completion-panel";
import { LessonTopBar } from "@/components/learning/lesson-top-bar";
import { LearningWorkspace } from "@/components/learning/workspace";

export const metadata: Metadata = { title: "The Nested Payload Problem · Trace", description: "Transfer the receiving-contract concept to nested task JSON, then return for retrieval." };

const LESSON = "fastapi-nested-payload-transfer";

export default function TransferPage() {
  return <main id="main" className="shell">
    <LessonTopBar title="The nested payload" />
    <LearningWorkspace lessonId={LESSON}>
      <CompletionPanel lessonId={LESSON} />
    </LearningWorkspace>
  </main>;
}
