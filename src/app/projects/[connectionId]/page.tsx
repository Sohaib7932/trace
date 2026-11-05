import { Suspense } from "react";
import { PageHead } from "@/components/projects/page-head";
import { ProjectView } from "@/components/projects/project-view";
import { ProjectsGate } from "@/components/projects/shell";

export const metadata = { title: "Project · Trace" };

async function View({ params }: { params: Promise<{ connectionId: string }> }) {
  const { connectionId } = await params;
  return <ProjectsGate next={`/projects/${encodeURIComponent(connectionId)}`}><ProjectView connectionId={connectionId} /></ProjectsGate>;
}

export default function ProjectPage({ params }: { params: Promise<{ connectionId: string }> }) {
  return (
    <>
      <PageHead title={["From commit to ", { accent: "questions" }]}>Pin one commit, let Trace read it, then work through questions tied to exact files and lines.</PageHead>
      <Suspense fallback={<span role="status" className="skeleton block h-40 rounded-[20px]" />}><View params={params} /></Suspense>
    </>
  );
}
