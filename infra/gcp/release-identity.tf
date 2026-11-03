resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "${var.name}-github"
  display_name              = "Trace protected production releases"
  depends_on                = [google_project_service.required]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "protected-release"
  attribute_mapping = {
    "google.subject"                = "assertion.sub"
    "attribute.repository_id"       = "assertion.repository_id"
    "attribute.repository_owner_id" = "assertion.repository_owner_id"
    "attribute.ref"                 = "assertion.ref"
  }
  attribute_condition = join(" && ", [
    "assertion.repository_id == '${var.github_repository_id}'",
    "assertion.repository_owner_id == '${var.github_owner_id}'",
    "assertion.ref == 'refs/heads/main'",
    "assertion.sub == 'repo:Sohaib7932/trace:environment:production'",
  ])
  oidc { issuer_uri = "https://token.actions.githubusercontent.com" }
}

resource "google_service_account" "release" {
  for_each     = toset(["runtime", "migrator"])
  account_id   = "${var.name}-release-${each.key}"
  display_name = "Trace protected ${each.key} release automation"
}

resource "google_service_account_iam_member" "federation" {
  for_each           = google_service_account.release
  service_account_id = each.value.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository_id/${var.github_repository_id}"
}

resource "google_service_account_iam_member" "runtime_act_as" {
  service_account_id = google_service_account.runtime.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.release["runtime"].email}"
}

resource "google_service_account_iam_member" "migrator_act_as" {
  service_account_id = google_service_account.migrator.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.release["migrator"].email}"
}

resource "google_project_iam_custom_role" "runtime_release" {
  role_id     = "${replace(var.name, "-", "_")}_runtime_release"
  title       = "Trace existing service release"
  description = "No service creation, IAM mutation, SQL or secret access."
  permissions = ["run.services.get", "run.services.update", "run.operations.get"]
}

resource "google_project_iam_custom_role" "migration_release" {
  role_id     = "${replace(var.name, "-", "_")}_migration_release"
  title       = "Trace existing explicit migration job release"
  description = "No job creation, IAM mutation, SQL or secret access."
  permissions = ["run.jobs.get", "run.jobs.update", "run.jobs.run", "run.executions.get", "run.operations.get"]
}

resource "google_project_iam_member" "runtime_release" {
  project = var.project_id
  role    = google_project_iam_custom_role.runtime_release.name
  member  = "serviceAccount:${google_service_account.release["runtime"].email}"
  condition {
    title       = "only-trace-service"
    description = "Limit updates to the pre-provisioned Trace service."
    expression  = "resource.name.endsWith('/locations/${var.region}/services/${var.name}-api') || resource.name.matches('projects/[^/]+/locations/${var.region}/operations/[^/]+$')"
  }
}

resource "google_project_iam_member" "migration_release" {
  project = var.project_id
  role    = google_project_iam_custom_role.migration_release.name
  member  = "serviceAccount:${google_service_account.release["migrator"].email}"
  condition {
    title       = "only-trace-migration-job"
    description = "Limit updates/execution to the separately approved migration job."
    expression  = "resource.name.endsWith('/locations/${var.region}/jobs/${var.name}-migrate') || resource.name.matches('projects/[^/]+/locations/${var.region}/jobs/${var.name}-migrate/executions/[^/]+$') || resource.name.matches('projects/[^/]+/locations/${var.region}/operations/[^/]+$')"
  }
}

# Platform request logs contain paths and can contain sensitive query values.
# Application access logging is also disabled by the production entry point.
# Keep sanitized application logs and platform aggregate metrics instead.
resource "google_logging_project_exclusion" "request_payload_privacy" {
  name        = "${var.name}-exclude-request-urls"
  description = "Do not retain Trace HTTP request URLs in Cloud Logging."
  filter      = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${var.name}-api\" AND log_id(\"run.googleapis.com/requests\")"
}
