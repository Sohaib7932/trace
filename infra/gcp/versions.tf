terraform {
  required_version = ">= 1.10.0, < 2.0.0"

  # Supply an approved, access-restricted, versioned state bucket at init time.
  # This module never creates a billing account or a state bucket.
  backend "gcs" {}

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "7.30.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
