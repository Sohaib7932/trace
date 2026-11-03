locals {
  backend_image_prefix = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.backend.repository_id}/trace-backend"
}

resource "google_artifact_registry_repository" "backend" {
  project       = var.project_id
  location      = var.region
  repository_id = "${var.name}-backend"
  description   = "Private reviewed Trace OCI releases; preserve immutable rollback artifacts."
  format        = "DOCKER"
  mode          = "STANDARD_REPOSITORY"
  labels        = local.labels
  docker_config {
    immutable_tags = true
  }
  # No allUsers/allAuthenticatedUsers grant and no automatic cleanup policy.
  # A registry publisher is an independently approved operator, not a workload
  # identity or the read-only release automation identity.
  lifecycle {
    prevent_destroy = true
    precondition {
      condition     = length(var.hosting_approval_reference) >= 3
      error_message = "Registry provisioning requires the explicit paid-hosting approval record."
    }
  }
  depends_on = [google_project_service.required]
}

resource "google_artifact_registry_repository_iam_member" "release_reader" {
  for_each   = google_service_account.release
  project    = var.project_id
  location   = var.region
  repository = google_artifact_registry_repository.backend.repository_id
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${each.value.email}"
}
