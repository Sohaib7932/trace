# All identities, approvals, domains and image digests below are format fixtures.
# Mocked plan runs never use a cloud API, credential, secret payload or real state.
mock_provider "google" {
  mock_data "google_project" {
    override_during = plan
    defaults        = { number = "123456789012" }
  }
}

override_resource {
  target          = google_service_account.runtime
  override_during = plan
  values = {
    name  = "projects/trace-artifact-test/serviceAccounts/trace-runtime@trace-artifact-test.iam.gserviceaccount.com"
    email = "trace-runtime@trace-artifact-test.iam.gserviceaccount.com"
  }
}

override_resource {
  target          = google_service_account.migrator
  override_during = plan
  values = {
    name  = "projects/trace-artifact-test/serviceAccounts/trace-migrator@trace-artifact-test.iam.gserviceaccount.com"
    email = "trace-migrator@trace-artifact-test.iam.gserviceaccount.com"
  }
}

override_resource {
  target          = google_secret_manager_secret.private["gemini-api-key"]
  override_during = plan
  values          = { id = "projects/trace-artifact-test/secrets/trace-gemini-api-key" }
}

override_resource {
  target          = google_secret_manager_secret.private["migrator-database-url"]
  override_during = plan
  values          = { id = "projects/trace-artifact-test/secrets/trace-migrator-database-url" }
}

override_resource {
  target          = google_secret_manager_secret.private["database-ca"]
  override_during = plan
  values          = { id = "projects/trace-artifact-test/secrets/trace-database-ca" }
}

variables {
  project_id                           = "trace-artifact-test"
  region                               = "us-central1"
  release_owner                        = "synthetic-reviewer"
  accounting_scope                     = "synthetic-stable-scope"
  hosting_approval_reference           = "synthetic-hosting-review"
  monthly_budget_usd                   = 1
  billing_account_id                   = "000000-000000-000000"
  frontend_origin                      = "https://learn.trace.example"
  supabase_url                         = "https://synthetic-test.supabase.co"
  github_repository_id                 = "123456"
  github_owner_id                      = "654321"
  image                                = "us-central1-docker.pkg.dev/trace-artifact-test/trace-backend/trace-backend@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  tls_acceptance_reference             = "synthetic-tls-review"
  trusted_proxy_ips                    = ["192.0.2.1"]
  proxy_acceptance_reference           = "synthetic-proxy-review"
  cookie_topology_acceptance_reference = "synthetic-cookie-review"
  approved_registrable_domain          = "trace.example"
  api_hostname                         = "api.trace.example"
  domain_mapping_acceptance_reference  = "synthetic-dns-review"
}

run "defaults_never_activate_a_provider" {
  command = plan
  assert {
    condition     = length(google_cloud_run_v2_service.api) == 0 && length(google_cloud_run_v2_job.migrate) == 0 && length(google_secret_manager_secret_iam_member.runtime_gemini) == 0
    error_message = "The default artifact must not activate runtime, migration or Gemini secret access."
  }
  assert {
    condition     = google_secret_manager_secret.private["gemini-api-key"].secret_id == "trace-gemini-api-key" && output.runtime_ai_profile == "disabled"
    error_message = "Only an empty private key container may be prepared before separate activation."
  }
  assert {
    condition     = length(google_monitoring_alert_policy.database_disk_capacity) == 0
    error_message = "No storage-capacity monitoring may activate by default."
  }
}

run "disabled_runtime_and_migrator_have_no_key" {
  command = plan
  variables {
    enable_application   = true
    enable_migration_job = true
  }
  assert {
    condition = alltrue([
      for envs in [google_cloud_run_v2_service.api[0].template[0].containers[0].env, google_cloud_run_v2_job.migrate[0].template[0].template[0].containers[0].env] :
      !contains([for item in envs : item.name], "GEMINI_API_KEY") &&
      one([for item in envs : item.value if item.name == "TRACE_LLM_MODE"]) == "disabled" &&
      one([for item in envs : item.value if item.name == "TRACE_EMBEDDING_MODE"]) == "disabled" &&
      one([for item in envs : item.value if item.name == "TRACE_RETRIEVAL_MODE"]) == "lexical"
    ])
    error_message = "Disabled runtime and migrator must retain disabled providers and lexical retrieval without a key."
  }
}

run "approved_profile_is_runtime_only_and_zero_paid" {
  command = plan
  variables {
    enable_application                   = true
    enable_migration_job                 = true
    enable_live_gemini                   = true
    gemini_unbilled_project_confirmed    = true
    gemini_activation_approval_reference = "synthetic-provider-review"
    gemini_secret_version                = "7"
  }
  assert {
    condition = {
      for item in google_cloud_run_v2_service.api[0].template[0].containers[0].env : item.name => item.value
      if startswith(item.name, "TRACE_LLM_")
    } == local.gemini_text_env
    error_message = "The runtime must use exactly the bounded approved profile without deployment model overrides."
  }
  assert {
    condition = (
      local.runtime_env.TRACE_LLM_MODE == "gemini_free" &&
      local.runtime_env.TRACE_LLM_PROVIDER_ID == "gemini" &&
      local.runtime_env.TRACE_LLM_GENERATION_MODEL_ID == "gemini-3.5-flash-lite" &&
      local.runtime_env.TRACE_LLM_CONVERSATIONAL_MODEL_ID == "gemini-3.5-flash-lite" &&
      local.runtime_env.TRACE_LLM_CREDENTIAL_ENV_VAR == "GEMINI_API_KEY" &&
      local.runtime_env.TRACE_LLM_FREE_TIER_PROJECT_CONFIRMED == "true" &&
      local.runtime_env.TRACE_LLM_SPEND_LIMIT_MICROUSD == "0" &&
      local.runtime_env.TRACE_LLM_MAX_COST_PER_ATTEMPT_MICROUSD == "0" &&
      local.runtime_env.TRACE_LLM_MAX_RETRIES == "0" &&
      local.runtime_env.TRACE_LLM_MAX_OUTPUT_TOKENS == "4096" &&
      local.runtime_env.TRACE_LLM_TOTAL_TIMEOUT_SECONDS == "20" &&
      local.runtime_env.TRACE_EMBEDDING_MODE == "disabled" &&
      local.runtime_env.TRACE_RETRIEVAL_MODE == "lexical" &&
      local.runtime_env.TRACE_ACCOUNTING_MODE == "durable" &&
      local.runtime_env.TRACE_ACCOUNTING_SCOPE == "synthetic-stable-scope" &&
      local.runtime_env.TRACE_ACCOUNTING_MAX_ATTEMPTS == "20" &&
      local.runtime_env.TRACE_ACCOUNTING_MAX_IN_FLIGHT == "4" &&
      local.runtime_env.TRACE_ACCOUNTING_MAX_SUBJECT_IN_FLIGHT == "1" &&
      local.runtime_env.TRACE_ACCOUNTING_REQUESTS_PER_MINUTE == "10" &&
      output.runtime_ai_profile == "gemini-free-text-v1"
    )
    error_message = "Activation must not weaken the approved model, zero spend/retry policy, cumulative durable caps or ranking gate."
  }
  assert {
    condition = (
      length(google_secret_manager_secret_iam_member.runtime_gemini) == 1 &&
      google_secret_manager_secret_iam_member.runtime_gemini[0].member == "serviceAccount:${google_service_account.runtime.email}" &&
      google_secret_manager_secret_iam_member.runtime_gemini[0].member != "serviceAccount:${google_service_account.migrator.email}" &&
      google_secret_manager_secret_iam_member.runtime_gemini[0].role == "roles/secretmanager.secretAccessor" &&
      !contains(keys(local.runtime_env), "GEMINI_API_KEY") &&
      one([for item in google_cloud_run_v2_service.api[0].template[0].containers[0].env : item if item.name == "GEMINI_API_KEY"]).value_source[0].secret_key_ref[0].secret == "trace-gemini-api-key" &&
      one([for item in google_cloud_run_v2_service.api[0].template[0].containers[0].env : item if item.name == "GEMINI_API_KEY"]).value_source[0].secret_key_ref[0].version == "7"
    )
    error_message = "Only runtime may access the private immutable key version, never an inline key value."
  }
  assert {
    condition = (
      !contains([for item in google_cloud_run_v2_job.migrate[0].template[0].template[0].containers[0].env : item.name], "GEMINI_API_KEY") &&
      { for item in google_cloud_run_v2_job.migrate[0].template[0].template[0].containers[0].env : item.name => item.value if startswith(item.name, "TRACE_LLM_") } == { TRACE_LLM_MODE = "disabled" } &&
      google_secret_manager_secret_iam_member.migrator_db.secret_id != google_secret_manager_secret.private["gemini-api-key"].id &&
      google_secret_manager_secret_iam_member.ca["migrator"].secret_id != google_secret_manager_secret.private["gemini-api-key"].id
    )
    error_message = "The isolated migrator must not inherit runtime live settings or any Gemini key access."
  }
}

run "reject_missing_unbilled_attestation" {
  command = plan
  variables {
    enable_application                   = true
    enable_live_gemini                   = true
    gemini_activation_approval_reference = "synthetic-provider-review"
  }
  expect_failures = [var.enable_live_gemini]
}

run "reject_missing_provider_approval" {
  command = plan
  variables {
    enable_application                = true
    enable_live_gemini                = true
    gemini_unbilled_project_confirmed = true
  }
  expect_failures = [var.enable_live_gemini]
}

run "reject_activation_without_application" {
  command = plan
  variables {
    enable_live_gemini                   = true
    gemini_unbilled_project_confirmed    = true
    gemini_activation_approval_reference = "synthetic-provider-review"
  }
  expect_failures = [var.enable_live_gemini]
}

run "reject_mutable_key_alias" {
  command = plan
  variables { gemini_secret_version = "latest" }
  expect_failures = [var.gemini_secret_version]
}

run "reject_zero_key_version" {
  command = plan
  variables { gemini_secret_version = "0" }
  expect_failures = [var.gemini_secret_version]
}

run "reject_secret_shaped_approval_record" {
  command = plan
  variables { gemini_activation_approval_reference = "synthetic@invalid.example" }
  expect_failures = [var.gemini_activation_approval_reference]
}

run "reject_scope_that_overflows_derived_namespaces" {
  command = plan
  variables { accounting_scope = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" }
  expect_failures = [var.accounting_scope]
}

run "approved_capacity_alert_is_targeted_and_bounded" {
  command = plan
  variables {
    enable_application               = true
    enable_monitoring                = true
    monitoring_notification_channels = ["projects/trace-artifact-test/notificationChannels/1234"]
    monitoring_approval_reference    = "synthetic-monitoring-owner-review"
  }
  assert {
    condition = (
      length(google_monitoring_alert_policy.database_disk_capacity) == 1 &&
      toset(google_monitoring_alert_policy.database_disk_capacity[0].notification_channels) == toset(["projects/trace-artifact-test/notificationChannels/1234"]) &&
      google_monitoring_alert_policy.database_disk_capacity[0].conditions[0].condition_threshold[0].filter == "resource.type=\"cloudsql_database\" AND resource.labels.database_id=\"trace-artifact-test:trace-postgres\" AND metric.type=\"cloudsql.googleapis.com/database/disk/utilization\"" &&
      google_monitoring_alert_policy.database_disk_capacity[0].conditions[0].condition_threshold[0].threshold_value == 0.80 &&
      google_monitoring_alert_policy.database_disk_capacity[0].conditions[0].condition_threshold[0].comparison == "COMPARISON_GT" &&
      google_monitoring_alert_policy.database_disk_capacity[0].conditions[0].condition_threshold[0].duration == "300s" &&
      google_monitoring_alert_policy.database_disk_capacity[0].conditions[0].condition_threshold[0].evaluation_missing_data == "EVALUATION_MISSING_DATA_NO_OP" &&
      google_monitoring_alert_policy.database_disk_capacity[0].conditions[0].condition_threshold[0].aggregations[0].alignment_period == "60s" &&
      google_monitoring_alert_policy.database_disk_capacity[0].conditions[0].condition_threshold[0].aggregations[0].per_series_aligner == "ALIGN_MAX"
    )
    error_message = "The owner-approved alert must target only this PostgreSQL volume, use fraction units and bounded sustained threshold, and preserve missing-data uncertainty."
  }
}

run "reject_capacity_monitoring_without_owner_approval" {
  command = plan
  variables {
    enable_application               = true
    enable_monitoring                = true
    monitoring_notification_channels = ["projects/trace-artifact-test/notificationChannels/1234"]
  }
  # The existing shared gate fails first; dependents cannot be planned.
  expect_failures = [google_monitoring_uptime_check_config.readiness]
}

run "reject_capacity_monitoring_without_verified_channel" {
  command = plan
  variables {
    enable_application            = true
    enable_monitoring             = true
    monitoring_approval_reference = "synthetic-monitoring-owner-review"
  }
  expect_failures = [google_monitoring_uptime_check_config.readiness]
}

run "reject_percent_as_capacity_fraction" {
  command = plan
  variables { database_disk_utilization_threshold = 80 }
  expect_failures = [var.database_disk_utilization_threshold]
}

run "reject_capacity_threshold_too_near_exhaustion" {
  command = plan
  variables { database_disk_utilization_threshold = 0.96 }
  expect_failures = [var.database_disk_utilization_threshold]
}

run "reject_unreviewed_low_capacity_threshold" {
  command = plan
  variables { database_disk_utilization_threshold = 0.49 }
  expect_failures = [var.database_disk_utilization_threshold]
}
