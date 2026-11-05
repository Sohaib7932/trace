import { Suspense } from "react";
import { PageHead } from "@/components/projects/page-head";
import { PathView } from "@/components/projects/path-view";
import { ProjectsGate } from "@/components/projects/shell";

export const metadata = { title: "Learning path · Trace" };

type Props = { params: Promise<{ connectionId: string }>; searchParams: Promise<{ sha?: string }> };

async function View({ params, searchParams }: Props) {
  const [{ connectionId }, { sha }] = await Promise.all([params, searchParams]);
  return <ProjectsGate next={`/projects/${encodeURIComponent(connectionId)}/path`}><PathView connectionId={connectionId} sha={sha} /></ProjectsGate>;
}

export default function PathPage(props: Props) {
  return (
    <>
      <PageHead title={["Your ", { accent: "learning path" }]}>Short questions written from your own code. Practice only: nothing here is graded.</PageHead>
      <Suspense fallback={<span role="status" className="skeleton block h-40 rounded-[20px]" />}><View {...props} /></Suspense>
    </>
  );
}
