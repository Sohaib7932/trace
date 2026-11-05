"use client";

import { ProjectsHub } from "./hub";
import { ProjectsGate, ProjectsProviders } from "./shell";

/** The Projects home as one component (providers, sign-in gate and hub), for callers that mount it directly. */
export function GitHubProjects() {
  return <ProjectsProviders><ProjectsGate next="/projects"><ProjectsHub /></ProjectsGate></ProjectsProviders>;
}
