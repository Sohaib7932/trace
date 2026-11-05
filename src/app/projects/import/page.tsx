import { Suspense } from "react";
import { ImportView } from "@/components/projects/import-view";
import { PageHead } from "@/components/projects/page-head";
import { ProjectsGate } from "@/components/projects/shell";

export const metadata = { title: "Choose repositories · Trace" };

async function Picker({ searchParams }: { searchParams: Promise<{ installation?: string }> }) {
  const { installation } = await searchParams;
  const id = installation && /^[1-9][0-9]{0,14}$/.test(installation) ? Number(installation) : undefined;
  return <ProjectsGate next="/projects/import"><ImportView installation={id} /></ProjectsGate>;
}

export default function ImportPage({ searchParams }: { searchParams: Promise<{ installation?: string }> }) {
  return (
    <>
      <PageHead title={["Choose your ", { accent: "repositories" }]}>Pick the ones to learn from. Nothing is read until you choose a commit.</PageHead>
      <Suspense fallback={<span role="status" className="skeleton block h-40 rounded-[20px]" />}><Picker searchParams={searchParams} /></Suspense>
    </>
  );
}
