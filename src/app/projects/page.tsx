import { SiteHeader } from "@/components/layout/site-header";
import { GitHubProjects } from "@/components/projects/github-projects";

export const metadata = { title: "Project Learning · Trace" };
export default function ProjectsPage() { return <><SiteHeader /><main id="main" className="shell py-12"><GitHubProjects /></main></>; }
