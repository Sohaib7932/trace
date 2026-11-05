import type { Metadata } from "next";
import { AmbientPage } from "@/components/layout/ambient-page";
import { SiteHeader } from "@/components/layout/site-header";
import { MotionRuntime } from "@/components/motion/motion-runtime";
import { ProjectsProviders } from "@/components/projects/shell";

// Private, account-only pages: never indexed, and no repository or file names in metadata.
export const metadata: Metadata = { title: "Projects · Trace", robots: { index: false, follow: false }, referrer: "no-referrer" };

export default function ProjectsLayout({ children }: { children: React.ReactNode }) {
  return (
    <AmbientPage calm>
      <SiteHeader cta={null} />
      <ProjectsProviders>
        <main id="main" className="shell pb-[clamp(64px,8vw,120px)]">{children}</main>
      </ProjectsProviders>
      <MotionRuntime />
    </AmbientPage>
  );
}
