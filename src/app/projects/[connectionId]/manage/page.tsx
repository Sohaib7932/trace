import { Suspense } from "react";
import { ManageView } from "@/components/projects/manage-view";
import { PageHead } from "@/components/projects/page-head";
import { ProjectsGate } from "@/components/projects/shell";

export const metadata = { title: "Manage project · Trace" };

async function View({ params }: { params: Promise<{ connectionId: string }> }) {
  const { connectionId } = await params;
  return <ProjectsGate next={`/projects/${encodeURIComponent(connectionId)}/manage`}><ManageView connectionId={connectionId} /></ProjectsGate>;
}

export default function ManagePage({ params }: { params: Promise<{ connectionId: string }> }) {
  return (
    <>
      <PageHead title={["Manage ", { accent: "access" }]}>See what Trace holds and stop access whenever you want.</PageHead>
      <Suspense fallback={<span role="status" className="skeleton block h-40 rounded-[20px]" />}><View params={params} /></Suspense>
    </>
  );
}
