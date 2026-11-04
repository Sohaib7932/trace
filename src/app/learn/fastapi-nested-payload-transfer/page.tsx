import type { Metadata } from "next";
import { CompletionPanel } from "@/components/learning/completion-panel";
import { AmbientPage } from "@/components/layout/ambient-page";
import { SiteHeader } from "@/components/layout/site-header";
import { createCta } from "@/components/layout/nav-links";
import { LearningWorkspace } from "@/components/learning/workspace";

export const metadata: Metadata = { title: "The Nested Payload Problem · Trace", description: "Transfer the receiving-contract concept to nested task JSON, then return for retrieval." };

const LESSON = "fastapi-nested-payload-transfer";

export default function TransferPage() {
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
