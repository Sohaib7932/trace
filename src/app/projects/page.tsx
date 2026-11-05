import { PageHead } from "@/components/projects/page-head";
import { ProjectsHub } from "@/components/projects/hub";
import { ProjectsGate } from "@/components/projects/shell";

export const metadata = { title: "Projects · Trace" };

export default function ProjectsPage() {
  return (
    <>
      <PageHead title={["Learn from your ", { accent: "own code" }]}>Connect GitHub, choose a repository, and get short questions about the code you actually wrote. Read-only, private, and tied to an exact commit.</PageHead>
      <ProjectsGate next="/projects"><ProjectsHub /></ProjectsGate>
    </>
  );
}
