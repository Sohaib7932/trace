variable "project_id" {
  type        = string
  description = "Existing approved GCP project. No project/billing account is created."
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "Supply the approved project ID."
  }
}

variable "region" {
  type        = string
  description = "Explicit approved same-region placement; no residency policy is inferred."
  validation {
    condition     = can(regex("^[a-z]+-[a-z]+[0-9]$", var.region))
    error_message = "Supply an approved GCP region."
  }
}

variable "name" {
  type    = string
  default = "trace"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,18}$", var.name))
    error_message = "Use a short lowercase resource prefix."
  }
}

variable "release_owner" {
  type        = string
  description = "Non-secret accountable team/role label, not a personal email."
  validation {
    condition     = can(regex("^[a-z0-9_-]{2,63}$", var.release_owner))
    error_message = "An accountable non-secret owner label is required."
  }
}

variable "accounting_scope" {
  type        = string
  description = "Explicit stable operator allowance/admission scope, at most 78 characters to leave derived namespace room. Preserve across replicas, restarts and releases; never rotate to refill quota."
  validation {
    condition     = can(regex("^[a-zA-Z0-9][a-zA-Z0-9_.:/-]{0,77}$", var.accounting_scope))
    error_message = "Supply a stable approved accounting scope matching the backend contract."
  }
}

variable "enable_monitoring" {
  type        = bool
  default     = false
  description = "Create reviewable monitoring resources only after deployment, notification and cost approval. No monitoring is provisioned by default."
}

variable "monitoring_notification_channels" {
  type        = list(string)
  default     = []
  description = "Existing operator-owned verified Monitoring channel resource IDs. No contacts are invented or created."
  validation {
    condition = alltrue([
      for value in var.monitoring_notification_channels :
      can(regex("^projects/[a-z0-9-]+/notificationChannels/[A-Za-z0-9_-]+$", value))
    ])
    error_message = "Use existing canonical notification-channel resource IDs, not email addresses, URLs or credentials."
  }
}

variable "monitoring_approval_reference" {
  type        = string
  default     = ""
  description = "Owner-approved alert thresholds, notification test, polling ownership and monitoring-cost review record."
}

variable "http_5xx_count_threshold" {
  type        = number
  default     = 4
  description = "Initial engineering alert fires above this count in a five-minute window; not a measured SLO."
  validation {
    condition     = var.http_5xx_count_threshold >= 0 && var.http_5xx_count_threshold <= 10000 && floor(var.http_5xx_count_threshold) == var.http_5xx_count_threshold
    error_message = "Use a bounded nonnegative integer alert threshold."
  }
}

variable "auth_error_count_threshold" {
  type        = number
  default     = 19
  description = "Initial per-status 401/403/429 count threshold per five minutes; an investigation signal, not proof of abuse."
  validation {
    condition     = var.auth_error_count_threshold >= 0 && var.auth_error_count_threshold <= 10000 && floor(var.auth_error_count_threshold) == var.auth_error_count_threshold
    error_message = "Use a bounded nonnegative integer alert threshold."
  }
}

variable "ai_unavailable_count_threshold" {
  type        = number
  default     = 4
  description = "Initial per-family unavailable/error delivery threshold per five minutes, including HTTP 200 unavailable states."
  validation {
    condition     = var.ai_unavailable_count_threshold >= 0 && var.ai_unavailable_count_threshold <= 10000 && floor(var.ai_unavailable_count_threshold) == var.ai_unavailable_count_threshold
    error_message = "Use a bounded nonnegative integer alert threshold."
  }
}

variable "database_disk_utilization_threshold" {
  type        = number
  default     = 0.80
  description = "Initial engineering storage-pressure fraction, not a percentage or measured SLO. Requires monitoring owner review; no automatic deletion or capacity increase."
  validation {
    condition     = var.database_disk_utilization_threshold >= 0.50 && var.database_disk_utilization_threshold <= 0.95
    error_message = "Use a reviewed disk-quota fraction between 0.50 and 0.95."
  }
}

variable "hosting_approval_reference" {
  type        = string
  description = "Recorded approval for this paid hosting plan; an identifier, never a credential."
  validation {
    condition     = can(regex("^[A-Za-z0-9_./:-]{3,128}$", var.hosting_approval_reference))
    error_message = "A hosting approval record is required before planning resources."
  }
}

variable "monthly_budget_usd" {
  type        = number
  description = "Approved monitoring threshold, not an automatic spending cap. No default or approval is implied."
  validation {
    condition     = var.monthly_budget_usd > 0 && var.monthly_budget_usd <= 10000 && floor(var.monthly_budget_usd) == var.monthly_budget_usd
    error_message = "Supply an explicitly approved positive monthly hosting budget."
  }
}

variable "billing_account_id" {
  type        = string
  description = "Existing approved billing account ID for a project-filtered alert budget. No billing is activated here."
  validation {
    condition     = can(regex("^[A-Fa-f0-9]{6}-[A-Fa-f0-9]{6}-[A-Fa-f0-9]{6}$", var.billing_account_id))
    error_message = "Supply the approved billing account ID privately through operator configuration."
  }
}

variable "enable_application" {
  type        = bool
  default     = false
  description = "Two-stage bootstrap. Keep false until secrets, DB roles, TLS and proxy acceptance are verified."
}

variable "enable_migration_job" {
  type        = bool
  default     = false
  description = "Enable the isolated job separately so schema migration/grants can precede application creation."
}

variable "enable_live_gemini" {
  type        = bool
  default     = false
  description = "Optional runtime-only approved free-text profile. Never enables embeddings or grants the migrator provider access."
  validation {
    condition = !var.enable_live_gemini || (
      var.enable_application && var.gemini_unbilled_project_confirmed &&
      can(regex("^[A-Za-z0-9_./:-]{3,128}$", var.gemini_activation_approval_reference))
    )
    error_message = "Live Gemini requires application activation, explicit existing unbilled-project attestation and a separate provider activation approval record."
  }
}

variable "gemini_unbilled_project_confirmed" {
  type        = bool
  default     = false
  description = "Operator attestation that the privately supplied key belongs to the approved Free Tier project with billing disabled. Terraform cannot inspect or prove that property."
}

variable "gemini_activation_approval_reference" {
  type        = string
  default     = ""
  description = "Non-secret approval record for this hosted free-text activation, model, key project and cumulative allowance; distinct from paid hosting approval."
  validation {
    condition     = var.gemini_activation_approval_reference == "" || can(regex("^[A-Za-z0-9_./:-]{3,128}$", var.gemini_activation_approval_reference))
    error_message = "Use a bounded approval record identifier, never credentials, email addresses or secret material."
  }
}

variable "gemini_secret_version" {
  type        = string
  default     = "1"
  description = "Immutable numeric version of the privately populated Gemini key container. No key value enters Terraform or the migrator."
  validation {
    condition     = can(regex("^[1-9][0-9]*$", var.gemini_secret_version))
    error_message = "Pin a positive numeric Gemini secret version; never latest."
  }
}

variable "tls_acceptance_reference" {
  type        = string
  default     = ""
  description = "Verified private routing, real CA/SAN identity and wrong-host/untrusted-CA rejection evidence."
}

variable "image" {
  type        = string
  default     = ""
  description = "Approved OCI image pinned by SHA-256; required when enabling application resources."
  validation {
    condition     = var.image == "" || can(regex("^[a-z0-9.-]+/[A-Za-z0-9_./-]+@sha256:[a-f0-9]{64}$", var.image))
    error_message = "Use an immutable registry image@sha256 digest, never a mutable tag."
  }
}

variable "frontend_origin" {
  type        = string
  description = "Exact approved HTTPS Vercel/custom frontend origin without path or wildcard."
  validation {
    condition     = can(regex("^https://[A-Za-z0-9.-]+(:443)?$", var.frontend_origin))
    error_message = "Supply one exact HTTPS frontend origin."
  }
}

variable "supabase_url" {
  type        = string
  description = "Existing public HTTPS Supabase Auth project URL; no keys or tokens."
  validation {
    condition     = can(regex("^https://[a-z0-9-]+\\.supabase\\.co$", var.supabase_url))
    error_message = "Supply the existing HTTPS Supabase project URL."
  }
}

variable "approved_registrable_domain" {
  type        = string
  default     = ""
  description = "Team-owned registrable domain verified by the DNS/TLS owner; required for same-site production activation."
  validation {
    condition = var.approved_registrable_domain == "" || (
      length(var.approved_registrable_domain) <= 253 &&
      can(regex("^[a-z0-9][a-z0-9.-]*\\.[a-z]{2,63}$", var.approved_registrable_domain)) &&
      !contains(["vercel.app", "run.app", "github.io", "netlify.app", "firebaseapp.com"], var.approved_registrable_domain)
    )
    error_message = "Supply an approved owned domain, not a shared hosting/public-suffix domain. Ownership and public-suffix review remain operator requirements."
  }
}

variable "api_hostname" {
  type        = string
  default     = ""
  description = "Approved HTTPS API custom hostname under the same owned registrable domain as the frontend; no automatic regional domain mapping."
  validation {
    condition     = var.api_hostname == "" || (length(var.api_hostname) <= 253 && can(regex("^[a-z0-9][a-z0-9.-]*\\.[a-z]{2,63}$", var.api_hostname)))
    error_message = "Supply a reviewed custom DNS hostname without scheme, path, port or wildcard."
  }
}

variable "domain_mapping_acceptance_reference" {
  type        = string
  default     = ""
  description = "DNS/TLS owner approval and tested custom HTTPS host routing/certificate evidence. Actual mapping is an external release prerequisite."
}

variable "trusted_proxy_ips" {
  type        = list(string)
  default     = []
  description = "Operator-verified Cloud Run socket peer IPs/CIDRs; empty cannot enable the application. No header-derived or wildcard trust."
  validation {
    condition = alltrue([
      for value in var.trusted_proxy_ips :
      (can(cidrhost(value, 0)) || can(cidrhost("${value}/32", 0)) || can(cidrhost("${value}/128", 0))) &&
      try(tonumber(split("/", value)[1]) > 0, true) && value != "*"
    ])
    error_message = "Only explicit IP addresses or nonzero-prefix CIDRs are allowed."
  }
}

variable "proxy_acceptance_reference" {
  type        = string
  default     = ""
  description = "Evidence record verifying the actual trusted peer, spoofed forwarding rejection and HTTPS scheme propagation."
}

variable "cookie_topology_acceptance_reference" {
  type        = string
  default     = ""
  description = "Verified same-site HTTPS frontend/API guest-cookie and history-claim evidence; CORS alone is insufficient."
}

variable "secret_versions" {
  type = object({
    runtime_database_url  = string
    migrator_database_url = string
    database_ca           = string
  })
  default = {
    runtime_database_url  = "1"
    migrator_database_url = "1"
    database_ca           = "1"
  }
  description = "Numeric immutable Secret Manager versions populated privately after infrastructure bootstrap. Payloads must never enter Terraform."
  validation {
    condition     = alltrue([for value in values(var.secret_versions) : can(regex("^[1-9][0-9]*$", value))])
    error_message = "Pin numeric secret versions; do not use latest."
  }
}

variable "database_tier" {
  type        = string
  default     = "db-custom-1-3840"
  description = "Initial Enterprise zonal engineering size; paid, unbenchmarked and subject to owner capacity approval."
  validation {
    condition     = can(regex("^db-custom-[0-9]+-[0-9]+$", var.database_tier))
    error_message = "Supply an explicitly reviewed Cloud SQL Enterprise custom tier."
  }
}

variable "github_repository_id" {
  type        = string
  description = "Immutable numeric GitHub repository ID, obtained read-only by the operator."
  validation {
    condition     = can(regex("^[1-9][0-9]*$", var.github_repository_id))
    error_message = "Supply the immutable GitHub repository ID."
  }
}

variable "github_owner_id" {
  type        = string
  description = "Immutable numeric repository-owner ID; prevents name-reuse impersonation."
  validation {
    condition     = can(regex("^[1-9][0-9]*$", var.github_owner_id))
    error_message = "Supply the immutable GitHub owner ID."
  }
}
