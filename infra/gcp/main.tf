locals {
  frontend_hostname = trimprefix(trimsuffix(var.frontend_origin, ":443"), "https://")
  labels = {
    app     = var.name
    owner   = var.release_owner
    managed = "terraform"
  }
  required_apis = toset([
    "artifactregistry.googleapis.com", "cloudresourcemanager.googleapis.com",
    "compute.googleapis.com", "iam.googleapis.com", "iamcredentials.googleapis.com",
    "run.googleapis.com", "secretmanager.googleapis.com", "servicenetworking.googleapis.com",
    "monitoring.googleapis.com", "logging.googleapis.com",
    "sqladmin.googleapis.com", "sts.googleapis.com", "billingbudgets.googleapis.com",
  ])
  # Containers only: an operator privately supplies immutable numbered versions.
  secret_names = toset(["runtime-database-url", "migrator-database-url", "database-ca", "gemini-api-key"])
  common_env = {
    TRACE_ENVIRONMENT                        = "production"
    TRACE_DATABASE_SCHEMA                    = "trace"
    TRACE_DATABASE_POOL_SIZE                 = "4"
    TRACE_DATABASE_MAX_OVERFLOW              = "0"
    TRACE_DATABASE_POOL_TIMEOUT_SECONDS      = "3"
    TRACE_DATABASE_POOL_RECYCLE_SECONDS      = "300"
    TRACE_DATABASE_TIMEOUT_SECONDS           = "3"
    TRACE_DATABASE_STATEMENT_TIMEOUT_SECONDS = "5"
    TRACE_DATABASE_LOCK_TIMEOUT_SECONDS      = "3"
    TRACE_CORS_ORIGINS                       = jsonencode([var.frontend_origin])
    TRACE_COOKIE_SECURE                      = "true"
    TRACE_ALLOW_INSECURE_LOCAL_COOKIES       = "false"
    TRACE_AUTH_ALLOW_INSECURE_LOOPBACK       = "false"
    TRACE_LOG_LEVEL                          = "INFO"
    TRACE_SUPABASE_URL                       = var.supabase_url
    TRACE_SUPABASE_ISSUER                    = "${var.supabase_url}/auth/v1"
    TRACE_SUPABASE_JWKS_URL                  = "${var.supabase_url}/auth/v1/.well-known/jwks.json"
    TRACE_SUPABASE_AUDIENCE                  = "authenticated"
    TRACE_LLM_MODE                           = "disabled"
    TRACE_EMBEDDING_MODE                     = "disabled"
    TRACE_RETRIEVAL_MODE                     = "lexical"
    TRACE_ACCOUNTING_MODE                    = "durable"
    TRACE_ACCOUNTING_SCOPE                   = var.accounting_scope
    TRACE_ACCOUNTING_MAX_ATTEMPTS            = "20"
    TRACE_ACCOUNTING_MAX_IN_FLIGHT           = "4"
    TRACE_ACCOUNTING_MAX_SUBJECT_IN_FLIGHT   = "1"
    TRACE_ACCOUNTING_REQUESTS_PER_MINUTE     = "10"
  }
  # Exact approved gemini-free-text-v1 profile; no model, paid, retry or
  # embedding override is accepted through deployment inputs.
  gemini_text_env = {
    TRACE_LLM_MODE                          = "gemini_free"
    TRACE_LLM_PROVIDER_ID                   = "gemini"
    TRACE_LLM_GENERATION_MODEL_ID           = "gemini-3.5-flash-lite"
    TRACE_LLM_CONVERSATIONAL_MODEL_ID       = "gemini-3.5-flash-lite"
    TRACE_LLM_CREDENTIAL_ENV_VAR            = "GEMINI_API_KEY"
    TRACE_LLM_FREE_TIER_PROJECT_CONFIRMED   = "true"
    TRACE_LLM_SPEND_LIMIT_MICROUSD          = "0"
    TRACE_LLM_MAX_COST_PER_ATTEMPT_MICROUSD = "0"
    TRACE_LLM_MAX_RETRIES                   = "0"
    TRACE_LLM_MAX_REQUEST_BYTES             = "32768"
    TRACE_LLM_MAX_RESPONSE_BYTES            = "16384"
    TRACE_LLM_MAX_INPUT_TOKENS              = "16384"
    TRACE_LLM_MAX_OUTPUT_TOKENS             = "4096"
    TRACE_LLM_CONNECT_TIMEOUT_SECONDS       = "3"
    TRACE_LLM_RESPONSE_TIMEOUT_SECONDS      = "10"
    TRACE_LLM_TOTAL_TIMEOUT_SECONDS         = "20"
    TRACE_LLM_REQUESTS_PER_MINUTE           = "10"
    TRACE_LLM_MAX_SUBJECTS                  = "1000"
    TRACE_LLM_MAX_LIVE_REQUESTS_PER_PROCESS = "20"
    TRACE_LLM_MAX_IN_FLIGHT                 = "4"
  }
  runtime_env = merge(
    local.common_env,
    var.enable_live_gemini ? local.gemini_text_env : {},
    { TRACE_TRUSTED_PROXY_IPS = join(",", var.trusted_proxy_ips) },
  )
}

resource "google_project_service" "required" {
  for_each           = local.required_apis
  service            = each.key
  disable_on_destroy = false
}

data "google_project" "current" {}

resource "google_billing_budget" "hosting" {
  billing_account = var.billing_account_id
  display_name    = "${var.name}-hosting-owner-approved-alert"
  budget_filter {
    projects               = ["projects/${data.google_project.current.number}"]
    credit_types_treatment = "INCLUDE_ALL_CREDITS"
  }
  amount {
    specified_amount {
      currency_code = "USD"
      units         = floor(var.monthly_budget_usd)
    }
  }
  threshold_rules { threshold_percent = 0.5 }
  threshold_rules { threshold_percent = 0.9 }
  threshold_rules { threshold_percent = 1.0 }
  # Alerts notify billing administrators/users by the platform default. They do
  # not stop spend; the release owner must approve an actual response procedure.
  depends_on = [google_project_service.required]
}

resource "google_compute_network" "private" {
  name                    = "${var.name}-private"
  auto_create_subnetworks = false
  depends_on              = [google_project_service.required]
}

resource "google_compute_subnetwork" "run" {
  name                     = "${var.name}-run"
  region                   = var.region
  network                  = google_compute_network.private.id
  ip_cidr_range            = "10.40.0.0/24"
  private_ip_google_access = true
}

resource "google_compute_global_address" "sql" {
  name          = "${var.name}-sql-private-services"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = google_compute_network.private.id
}

resource "google_service_networking_connection" "sql" {
  network                 = google_compute_network.private.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.sql.name]
}

resource "google_sql_database_instance" "trace" {
  name                = "${var.name}-postgres"
  region              = var.region
  database_version    = "POSTGRES_17"
  deletion_protection = true
  settings {
    edition                     = "ENTERPRISE"
    tier                        = var.database_tier
    availability_type           = "ZONAL"
    disk_type                   = "PD_SSD"
    disk_size                   = 20
    disk_autoresize             = true
    disk_autoresize_limit       = 100
    deletion_protection_enabled = true
    user_labels                 = local.labels
    ip_configuration {
      ipv4_enabled    = false
      private_network = google_compute_network.private.id
      ssl_mode        = "ENCRYPTED_ONLY"
      # Shared CA supplies DNS SAN identity for private-services-access clients.
      server_ca_mode = "GOOGLE_MANAGED_CAS_CA"
    }
    backup_configuration {
      enabled                        = true
      start_time                     = "02:00"
      point_in_time_recovery_enabled = true
      transaction_log_retention_days = 7
      backup_retention_settings {
        retained_backups = 14
        retention_unit   = "COUNT"
      }
    }
    maintenance_window {
      day          = 7
      hour         = 3
      update_track = "stable"
    }
  }
  depends_on = [google_service_networking_connection.sql]
  lifecycle {
    prevent_destroy = true
    precondition {
      condition     = length(var.hosting_approval_reference) >= 3
      error_message = "Paid hosting requires an explicit owner approval record."
    }
  }
}

resource "google_sql_database" "trace" {
  name     = "trace"
  instance = google_sql_database_instance.trace.name
}

resource "google_secret_manager_secret" "private" {
  for_each  = local.secret_names
  secret_id = "${var.name}-${each.key}"
  labels    = local.labels
  replication {
    auto {}
  }
  depends_on = [google_project_service.required]
  lifecycle { prevent_destroy = true }
}

resource "google_service_account" "runtime" {
  account_id   = "${var.name}-runtime"
  display_name = "Trace runtime; no schema ownership"
}

resource "google_service_account" "migrator" {
  account_id   = "${var.name}-migrator"
  display_name = "Trace explicit one-shot migrator"
}

resource "google_secret_manager_secret_iam_member" "runtime_db" {
  secret_id = google_secret_manager_secret.private["runtime-database-url"].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_secret_manager_secret_iam_member" "migrator_db" {
  secret_id = google_secret_manager_secret.private["migrator-database-url"].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.migrator.email}"
}

resource "google_secret_manager_secret_iam_member" "runtime_gemini" {
  count     = var.enable_live_gemini ? 1 : 0
  secret_id = google_secret_manager_secret.private["gemini-api-key"].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_secret_manager_secret_iam_member" "ca" {
  for_each  = { runtime = google_service_account.runtime.email, migrator = google_service_account.migrator.email }
  secret_id = google_secret_manager_secret.private["database-ca"].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${each.value}"
}

resource "google_cloud_run_v2_service" "api" {
  count               = var.enable_application ? 1 : 0
  name                = "${var.name}-api"
  location            = var.region
  deletion_protection = true
  ingress             = "INGRESS_TRAFFIC_ALL"
  labels              = local.labels
  template {
    service_account                  = google_service_account.runtime.email
    execution_environment            = "EXECUTION_ENVIRONMENT_GEN2"
    timeout                          = "60s"
    max_instance_request_concurrency = 8
    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }
    vpc_access {
      egress = "PRIVATE_RANGES_ONLY"
      network_interfaces {
        network    = google_compute_network.private.name
        subnetwork = google_compute_subnetwork.run.name
      }
    }
    containers {
      image = var.image
      ports { container_port = 8000 }
      resources {
        limits            = { cpu = "1", memory = "1Gi" }
        cpu_idle          = true
        startup_cpu_boost = false
      }
      dynamic "env" {
        for_each = local.runtime_env
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = var.enable_live_gemini ? [var.gemini_secret_version] : []
        content {
          name = "GEMINI_API_KEY"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.private["gemini-api-key"].secret_id
              version = env.value
            }
          }
        }
      }
      env {
        name = "TRACE_DATABASE_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.private["runtime-database-url"].secret_id
            version = var.secret_versions.runtime_database_url
          }
        }
      }
      volume_mounts {
        name       = "database-ca"
        mount_path = "/var/run/trace-db-tls"
      }
      startup_probe {
        tcp_socket { port = 8000 }
        initial_delay_seconds = 5
        timeout_seconds       = 1
        period_seconds        = 5
        failure_threshold     = 24
      }
    }
    volumes {
      name = "database-ca"
      secret {
        secret = google_secret_manager_secret.private["database-ca"].secret_id
        items {
          version = var.secret_versions.database_ca
          path    = "server-ca.pem"
          mode    = 292 # POSIX 0444, expressed as a decimal integer.
        }
      }
    }
  }
  lifecycle {
    precondition {
      condition     = startswith(var.image, "${local.backend_image_prefix}@sha256:")
      error_message = "Use a reviewed immutable digest from the private Trace backend repository."
    }
    precondition {
      condition     = var.image != "" && length(var.tls_acceptance_reference) >= 3 && length(var.trusted_proxy_ips) > 0 && length(var.proxy_acceptance_reference) >= 3 && length(var.cookie_topology_acceptance_reference) >= 3
      error_message = "Activation requires a pinned image and reviewed database TLS, explicit proxy trust and guest-cookie topology evidence."
    }
    precondition {
      condition = (
        var.approved_registrable_domain != "" && var.api_hostname != local.frontend_hostname &&
        endswith(local.frontend_hostname, ".${var.approved_registrable_domain}") &&
        endswith(var.api_hostname, ".${var.approved_registrable_domain}") &&
        length(var.domain_mapping_acceptance_reference) >= 3
      )
      error_message = "Activation requires approved distinct frontend/API HTTPS subdomains under the same owned registrable domain and verified DNS/TLS routing."
    }
  }
  depends_on = [google_secret_manager_secret_iam_member.runtime_db, google_secret_manager_secret_iam_member.ca, google_secret_manager_secret_iam_member.runtime_gemini]
}

resource "google_cloud_run_v2_service_iam_member" "browser_invocation" {
  count    = var.enable_application ? 1 : 0
  name     = google_cloud_run_v2_service.api[0].name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
  # Public HTTPS transport is deliberate: Trace verifies Supabase JWTs and
  # ownership itself. This does not grant unauthenticated learner API access.
}

resource "google_cloud_run_v2_job" "migrate" {
  count               = var.enable_migration_job ? 1 : 0
  name                = "${var.name}-migrate"
  location            = var.region
  deletion_protection = true
  template {
    task_count  = 1
    parallelism = 1
    template {
      service_account = google_service_account.migrator.email
      max_retries     = 0
      timeout         = "600s"
      vpc_access {
        egress = "PRIVATE_RANGES_ONLY"
        network_interfaces {
          network    = google_compute_network.private.name
          subnetwork = google_compute_subnetwork.run.name
        }
      }
      containers {
        image   = var.image
        command = ["/app/.venv/bin/python", "-m", "scripts.migrate_production"]
        resources { limits = { cpu = "1", memory = "1Gi" } }
        dynamic "env" {
          for_each = local.common_env
          content {
            name  = env.key
            value = env.value
          }
        }
        env {
          name = "TRACE_DATABASE_URL"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.private["migrator-database-url"].secret_id
              version = var.secret_versions.migrator_database_url
            }
          }
        }
        volume_mounts {
          name       = "database-ca"
          mount_path = "/var/run/trace-db-tls"
        }
      }
      volumes {
        name = "database-ca"
        secret {
          secret = google_secret_manager_secret.private["database-ca"].secret_id
          items {
            version = var.secret_versions.database_ca
            path    = "server-ca.pem"
            mode    = 292 # POSIX 0444, expressed as a decimal integer.
          }
        }
      }
    }
  }
  lifecycle {
    precondition {
      condition     = startswith(var.image, "${local.backend_image_prefix}@sha256:")
      error_message = "Use the reviewed private Trace backend image digest for migrations."
    }
    precondition {
      condition     = var.image != "" && length(var.tls_acceptance_reference) >= 3
      error_message = "The migration job requires a pinned approved image and verified database TLS."
    }
  }
  depends_on = [google_secret_manager_secret_iam_member.migrator_db, google_secret_manager_secret_iam_member.ca]
}
