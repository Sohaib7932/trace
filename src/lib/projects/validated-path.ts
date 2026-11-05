import type { ProjectLearningPath, ProjectSnapshot } from "@/lib/api/github-projects";

/** A ready receipt must agree with both its pinned sources and provider attribution. */
export function isValidatedPath(value: ProjectLearningPath | undefined, snapshot: ProjectSnapshot | undefined, sha: string): boolean {
  return Boolean(value?.status === "ready" && value.content && value.id && value.generation && snapshot
    && snapshot.commit_sha === sha && value.commit_sha === sha && value.snapshot_digest === snapshot.digest
    && ((value.source === "ai" && value.generation.provider_id === "gemini")
      || (value.source === "test_fixture" && value.generation.provider_id === "mock"))
    && value.grading === "ungraded" && value.execution_status === "not_executed" && value.can_complete_lesson === false
    && value.content.steps.length > 0
    && value.content.steps.every((step) => step.reference_ids.length > 0
      && step.reference_ids.every((id) => snapshot.references.some((reference) => reference.reference_id === id))));
}
