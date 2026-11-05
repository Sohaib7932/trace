import { ConnectView } from "@/components/projects/connect";
import { PageHead } from "@/components/projects/page-head";
import { ProjectsGate } from "@/components/projects/shell";

export const metadata = { title: "Connect GitHub · Trace" };

export default function ConnectPage() {
  return (
    <>
      <PageHead title={["Connect ", { accent: "GitHub" }]}>You choose the repositories. Trace reads them read-only and shows you exactly what it kept.</PageHead>
      <ProjectsGate next="/projects/connect"><ConnectView /></ProjectsGate>
    </>
  );
}
