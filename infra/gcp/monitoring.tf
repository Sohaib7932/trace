# Artifacts only. All monitoring resources are absent unless explicitly enabled.
# No learner identity, question, answer, raw URL, token or vector becomes a label.
locals {
  run_metric_scope = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${var.name}-api\" AND resource.labels.location=\"${var.region}\""
  run_log_scope    = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${var.name}-api\""
}

resource "google_monitoring_uptime_check_config" "readiness" {
  count            = var.enable_monitoring ? 1 : 0
  display_name     = "${var.name}-https-readiness"
  timeout          = "10s"
  period           = "60s"
  selected_regions = ["USA", "EUROPE", "ASIA_PACIFIC"]
  http_check {
    path           = "/api/v1/health/ready"
    port           = 443
    use_ssl        = true
    validate_ssl   = true
    request_method = "GET"
    accepted_response_status_codes { status_value = 200 }
  }
  monitored_resource {
    type = "uptime_url"
    labels = {
      project_id = var.project_id
      host       = var.api_hostname
    }
  }
  content_matchers {
    content = jsonencode("ready")
    matcher = "MATCHES_JSON_PATH"
    json_path_matcher {
      json_path    = "$.status"
      json_matcher = "EXACT_MATCH"
    }
  }
  lifecycle {
    precondition {
      condition     = var.enable_application && length(var.monitoring_notification_channels) > 0 && length(var.monitoring_approval_reference) >= 3
      error_message = "Monitoring requires the approved application/custom host, verified operator notification channels and an explicit monitoring approval record."
    }
  }
  depends_on = [google_cloud_run_v2_service.api, google_project_service.required]
}

resource "google_logging_metric" "auth_errors" {
  count       = var.enable_monitoring ? 1 : 0
  name        = "${var.name}_sanitized_auth_errors"
  description = "Counts only allowlisted application 401/403/429 completion statuses. No identity or request content labels."
  filter      = "${local.run_log_scope} AND jsonPayload.event=\"request_complete\" AND (jsonPayload.status_code=401 OR jsonPayload.status_code=403 OR jsonPayload.status_code=429)"
  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
    labels {
      key         = "status_code"
      value_type  = "STRING"
      description = "Only 401, 403 or 429 selected by the counter filter."
    }
  }
  label_extractors = { status_code = "EXTRACT(jsonPayload.status_code)" }
  depends_on       = [google_monitoring_uptime_check_config.readiness]
}

resource "google_logging_metric" "ai_unavailable" {
  count       = var.enable_monitoring ? 1 : 0
  name        = "${var.name}_sanitized_ai_unavailable"
  description = "Bounded AI delivery unavailable/error events, including honest HTTP 200 unavailable responses. No semantic quality claim."
  filter = join(" AND ", [
    local.run_log_scope,
    "jsonPayload.event=\"ai_delivery\"",
    "(jsonPayload.ai_outcome=\"unavailable\" OR jsonPayload.ai_outcome=\"error\")",
    "(jsonPayload.ai_family=\"tutor\" OR jsonPayload.ai_family=\"support\" OR jsonPayload.ai_family=\"generation\" OR jsonPayload.ai_family=\"embedding\")",
    "(jsonPayload.ai_status=\"answered\" OR jsonPayload.ai_status=\"declined\" OR jsonPayload.ai_status=\"unavailable\" OR jsonPayload.ai_status=\"no_sources\" OR jsonPayload.ai_status=\"unsupported\" OR jsonPayload.ai_status=\"success\" OR jsonPayload.ai_status=\"refusal\" OR jsonPayload.ai_status=\"truncated\" OR jsonPayload.ai_status=\"timeout\" OR jsonPayload.ai_status=\"rate_limited\" OR jsonPayload.ai_status=\"transport_error\")",
    "(jsonPayload.ai_source=\"ai\" OR jsonPayload.ai_source=\"test_fixture\" OR jsonPayload.ai_source=\"none\" OR jsonPayload.ai_source=\"unavailable\")",
  ])
  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
    dynamic "labels" {
      for_each = toset(["ai_family", "ai_status", "ai_source"])
      content {
        key         = labels.value
        value_type  = "STRING"
        description = "Allowlisted structured AI delivery metadata only."
      }
    }
  }
  label_extractors = {
    ai_family = "EXTRACT(jsonPayload.ai_family)"
    ai_status = "EXTRACT(jsonPayload.ai_status)"
    ai_source = "EXTRACT(jsonPayload.ai_source)"
  }
  # JsonFormatter uses jsonPayload.level, not native Cloud Logging severity.
  # Match the validated event/outcome bundle rather than assuming a severity map.
  depends_on = [google_monitoring_uptime_check_config.readiness]
}

resource "google_monitoring_alert_policy" "http_5xx" {
  count                 = var.enable_monitoring ? 1 : 0
  display_name          = "${var.name}-http-5xx-burst"
  combiner              = "OR"
  notification_channels = var.monitoring_notification_channels
  user_labels           = local.labels
  conditions {
    display_name = "More than the approved five-minute 5xx count"
    condition_threshold {
      filter          = "${local.run_metric_scope} AND metric.type=\"run.googleapis.com/request_count\" AND metric.labels.response_code_class=\"5xx\""
      comparison      = "COMPARISON_GT"
      threshold_value = var.http_5xx_count_threshold
      duration        = "0s"
      aggregations {
        alignment_period     = "300s"
        per_series_aligner   = "ALIGN_SUM"
        cross_series_reducer = "REDUCE_SUM"
      }
      trigger { count = 1 }
    }
  }
  documentation {
    mime_type = "text/markdown"
    content   = "Investigate the approved revision and safe aggregate status. This metric counts only requests reaching a container and is not an availability SLO. Preserve evidence; do not expose request URLs, bodies, credentials or learner identities."
  }
  depends_on = [google_monitoring_uptime_check_config.readiness]
}

resource "google_monitoring_alert_policy" "readiness" {
  count                 = var.enable_monitoring ? 1 : 0
  display_name          = "${var.name}-https-readiness-failed"
  combiner              = "OR"
  notification_channels = var.monitoring_notification_channels
  user_labels           = local.labels
  conditions {
    display_name = "At least two checkers fail readiness for two minutes"
    condition_threshold {
      filter                  = "resource.type=\"uptime_url\" AND metric.type=\"monitoring.googleapis.com/uptime_check/check_passed\" AND metric.labels.check_id=\"${google_monitoring_uptime_check_config.readiness[0].uptime_check_id}\""
      comparison              = "COMPARISON_GT"
      threshold_value         = 1
      duration                = "120s"
      evaluation_missing_data = "EVALUATION_MISSING_DATA_NO_OP"
      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_NEXT_OLDER"
        cross_series_reducer = "REDUCE_COUNT_FALSE"
      }
      trigger { count = 1 }
    }
  }
  documentation {
    mime_type = "text/markdown"
    content   = "Check the approved HTTPS API hostname, certificate/proxy trust, current schema and database. The probe uses only the fixed public readiness path without credentials or learner data. Verify notification receipt and restoration in staging; missing time series are not proof of health."
  }
}

resource "google_monitoring_alert_policy" "database_up" {
  count                 = var.enable_monitoring ? 1 : 0
  display_name          = "${var.name}-postgres-not-up"
  combiner              = "OR"
  notification_channels = var.monitoring_notification_channels
  user_labels           = local.labels
  conditions {
    display_name = "Cloud SQL server reports down for three minutes"
    condition_threshold {
      filter                  = "resource.type=\"cloudsql_database\" AND resource.labels.database_id=\"${var.project_id}:${google_sql_database_instance.trace.name}\" AND metric.type=\"cloudsql.googleapis.com/database/up\""
      comparison              = "COMPARISON_LT"
      threshold_value         = 1
      duration                = "180s"
      evaluation_missing_data = "EVALUATION_MISSING_DATA_NO_OP"
      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_MIN"
      }
      trigger { count = 1 }
    }
  }
  documentation {
    mime_type = "text/markdown"
    content   = "Use the approved operator database/readiness and backup procedures. A managed server-up signal does not prove schema compatibility, permissions, source eligibility or recoverability. Cloud SQL sampling/ingestion is delayed; verify actual metric labels in staging. Do not reset the database or auto-refund leases."
  }
  depends_on = [google_monitoring_uptime_check_config.readiness]
}

resource "google_monitoring_alert_policy" "database_disk_capacity" {
  count                 = var.enable_monitoring ? 1 : 0
  display_name          = "${var.name}-postgres-disk-capacity-pressure"
  combiner              = "OR"
  notification_channels = var.monitoring_notification_channels
  user_labels           = local.labels
  conditions {
    display_name = "Cloud SQL disk-quota fraction remains above the reviewed threshold for five minutes"
    condition_threshold {
      filter                  = "resource.type=\"cloudsql_database\" AND resource.labels.database_id=\"${var.project_id}:${google_sql_database_instance.trace.name}\" AND metric.type=\"cloudsql.googleapis.com/database/disk/utilization\""
      comparison              = "COMPARISON_GT"
      threshold_value         = var.database_disk_utilization_threshold
      duration                = "300s"
      evaluation_missing_data = "EVALUATION_MISSING_DATA_NO_OP"
      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_MAX"
      }
      trigger { count = 1 }
    }
  }
  documentation {
    mime_type = "text/markdown"
    content   = "Review Cloud SQL storage growth, disk-usage categories, approved auto-resize ceiling, budget and backup/recovery evidence before capacity is exhausted. The metric is a fraction (0.80 means 80%), sampled every 60 seconds with up to 165 seconds of visibility delay. Missing data is not proof of available space. This monitors the managed database volume, not a developer workstation or container build disk. Do not delete learner data, reset the database or increase billable capacity automatically."
  }
  lifecycle {
    precondition {
      condition     = var.enable_application && length(var.monitoring_notification_channels) > 0 && length(var.monitoring_approval_reference) >= 3
      error_message = "Capacity monitoring requires approved application activation, verified operator notification channels and the monitoring-owner approval record."
    }
  }
  depends_on = [google_monitoring_uptime_check_config.readiness]
}

resource "google_monitoring_alert_policy" "auth_errors" {
  count                 = var.enable_monitoring ? 1 : 0
  display_name          = "${var.name}-auth-or-limit-burst"
  combiner              = "OR"
  notification_channels = var.monitoring_notification_channels
  user_labels           = local.labels
  conditions {
    display_name = "Per-status 401/403/429 five-minute count exceeds approved threshold"
    condition_threshold {
      filter          = "${local.run_metric_scope} AND metric.type=\"logging.googleapis.com/user/${google_logging_metric.auth_errors[0].name}\""
      comparison      = "COMPARISON_GT"
      threshold_value = var.auth_error_count_threshold
      duration        = "0s"
      aggregations {
        alignment_period     = "300s"
        per_series_aligner   = "ALIGN_SUM"
        cross_series_reducer = "REDUCE_SUM"
        group_by_fields      = ["metric.labels.status_code"]
      }
      trigger { count = 1 }
    }
  }
  documentation {
    mime_type = "text/markdown"
    content   = "Review aggregate authentication, ownership and admission behavior. A burst is an investigation signal, not proof of compromise; guest bootstrap can legitimately produce 401. Do not bypass authentication or increase quota automatically. No identity, request ID or raw path is a metric label."
  }
}

resource "google_monitoring_alert_policy" "ai_unavailable" {
  count                 = var.enable_monitoring ? 1 : 0
  display_name          = "${var.name}-ai-delivery-unavailable"
  combiner              = "OR"
  notification_channels = var.monitoring_notification_channels
  user_labels           = local.labels
  conditions {
    display_name = "Per-family unavailable/error delivery count exceeds approved threshold"
    condition_threshold {
      filter          = "${local.run_metric_scope} AND metric.type=\"logging.googleapis.com/user/${google_logging_metric.ai_unavailable[0].name}\""
      comparison      = "COMPARISON_GT"
      threshold_value = var.ai_unavailable_count_threshold
      duration        = "0s"
      aggregations {
        alignment_period     = "300s"
        per_series_aligner   = "ALIGN_SUM"
        cross_series_reducer = "REDUCE_SUM"
        group_by_fields      = ["metric.labels.ai_family"]
      }
      trigger { count = 1 }
    }
  }
  documentation {
    mime_type = "text/markdown"
    content   = "An honest unavailable response can use HTTP 200. Check configured modes, durable allowance, missing usage, source eligibility and provider errors using the safe operator status CLI. Do not enable paid fallback, retry batches or promote an unreviewed index. This alert measures delivery availability, not model correctness or grounded-answer quality."
  }
}
