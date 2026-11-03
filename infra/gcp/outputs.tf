output "private_database_ip" {
  value       = google_sql_database_instance.trace.private_ip_address
  description = "Routing address only. It is not automatically a verified TLS hostname."
}

output "database_instance_name" { value = google_sql_database_instance.trace.name }
output "runtime_service_account" { value = google_service_account.runtime.email }
output "migrator_service_account" { value = google_service_account.migrator.email }
output "release_service_account" { value = google_service_account.release["runtime"].email }
output "migration_release_service_account" { value = google_service_account.release["migrator"].email }
output "workload_identity_provider" { value = google_iam_workload_identity_pool_provider.github.name }
output "secret_container_ids" { value = { for key, secret in google_secret_manager_secret.private : key => secret.secret_id } }
output "service_url" { value = try(google_cloud_run_v2_service.api[0].uri, null) }
output "migration_job" { value = try(google_cloud_run_v2_job.migrate[0].name, null) }
output "approved_api_origin" {
  value       = var.api_hostname == "" ? null : "https://${var.api_hostname}"
  description = "Frontend API base URL only after approved custom DNS/TLS mapping and real-browser acceptance; run.app is not the guest integration URL."
}

output "readiness_uptime_check_id" {
  value       = try(google_monitoring_uptime_check_config.readiness[0].uptime_check_id, null)
  description = "Verify actual time-series selection and notifications in approved staging before relying on alerts."
}

output "backend_artifact_repository_id" {
  value       = google_artifact_registry_repository.backend.id
  description = "Private same-project regional DOCKER repository; no automatic image upload."
}

output "backend_image_prefix" {
  value       = local.backend_image_prefix
  description = "Set the protected environment GCP_IMAGE_PREFIX to this exact path; deploy only approved @sha256 digests."
}

output "runtime_ai_profile" {
  value       = var.enable_live_gemini ? "gemini-free-text-v1" : "disabled"
  description = "Configured runtime-only text profile, not proof of provider readiness, billing status or successful delivery. Embeddings remain disabled and retrieval remains lexical."
}
