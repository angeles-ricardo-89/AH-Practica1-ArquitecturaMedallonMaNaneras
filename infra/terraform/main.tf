terraform {
  required_version = ">= 1.9"
}

provider "google" {
  project = var.project
  region  = var.region
}

provider "random" {}

# ─── APIs necesarias (declarativas; no se deshabilitan en destroy) ───────────
resource "google_project_service" "run" {
  service            = "run.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "artifactregistry" {
  service            = "artifactregistry.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "secretmanager" {
  service            = "secretmanager.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "cloudbuild" {
  service            = "cloudbuild.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "generativelanguage" {
  service            = "generativelanguage.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "aiplatform" {
  service            = "aiplatform.googleapis.com"
  disable_on_destroy = false
}

# ─── Artifact Registry (imagen del build unico web+API) ───────────────────────
resource "google_artifact_registry_repository" "app" {
  location      = var.region
  repository_id = var.artifact_repo
  description   = "Imagen productiva web+API de Lakehouse Mananeras"
  format        = "DOCKER"
}

# ─── Secretos existentes (referenciados, no re-provisionados) ────────────────
data "google_secret_manager_secret" "gemini_api_key" {
  secret_id = var.existing_secrets.gemini_api_key
}

data "google_secret_manager_secret" "neon_db_url" {
  secret_id = var.existing_secrets.neon_db_url
}

data "google_secret_manager_secret" "telegram_bot_token" {
  secret_id = var.existing_secrets.telegram_bot_token
}

data "google_secret_manager_secret" "telegram_chat_id" {
  secret_id = var.existing_secrets.telegram_chat_id
}

# ─── Secretos nuevos con valores aleatorios (1 version cada uno) ─────────────
resource "random_password" "jwt_secret" {
  length  = 64
  special = false
}

resource "random_password" "csrf_secret" {
  length  = 64
  special = false
}

resource "random_password" "demo_user_1_password" {
  length  = 24
  special = true
}

resource "random_password" "demo_user_2_password" {
  length  = 24
  special = true
}

resource "google_secret_manager_secret" "jwt_secret" {
  secret_id = "JWT_SECRET"
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "jwt_secret" {
  secret      = google_secret_manager_secret.jwt_secret.id
  secret_data = random_password.jwt_secret.result
}

resource "google_secret_manager_secret" "csrf_secret" {
  secret_id = "CSRF_SECRET"
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "csrf_secret" {
  secret      = google_secret_manager_secret.csrf_secret.id
  secret_data = random_password.csrf_secret.result
}

resource "google_secret_manager_secret" "demo_user_1_password" {
  secret_id = "DEMO_USER_1_PASSWORD"
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "demo_user_1_password" {
  secret      = google_secret_manager_secret.demo_user_1_password.id
  secret_data = random_password.demo_user_1_password.result
}

resource "google_secret_manager_secret" "demo_user_2_password" {
  secret_id = "DEMO_USER_2_PASSWORD"
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "demo_user_2_password" {
  secret      = google_secret_manager_secret.demo_user_2_password.id
  secret_data = random_password.demo_user_2_password.result
}

# ─── Service account de Cloud Run con privilegios minimos ─────────────────────
resource "google_service_account" "cloudrun" {
  account_id   = "lakehouse-cloudrun"
  display_name = "Service account del servicio Cloud Run de Lakehouse Mananeras"
}

resource "google_project_iam_member" "cloudrun_secret_accessor" {
  project = var.project
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.cloudrun.email}"
}

# ─── Cloud Run: build unico web+API, escala a cero, 1 instancia ───────────────
resource "google_cloud_run_v2_service" "app" {
  name     = var.service_name
  location = var.region
  project  = var.project
  ingress  = "INGRESS_TRAFFIC_ALL"
  # La demo es IaC gestionada por Terraform (rollback = terraform destroy);
  # se permite recrear el servicio para cambios inmutables como el nombre.
  deletion_protection = false
  depends_on = [
    google_project_service.run,
    google_secret_manager_secret_version.jwt_secret,
    google_secret_manager_secret_version.csrf_secret,
    google_secret_manager_secret_version.demo_user_1_password,
    google_secret_manager_secret_version.demo_user_2_password,
  ]

  template {
    service_account = google_service_account.cloudrun.email
    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }
    containers {
      image = var.image
      name  = "app"
      resources {
        limits = {
          cpu    = var.cpu
          memory = var.memory
        }
        cpu_idle = true
      }
      env {
        name  = "APP_ENV"
        value = "production"
      }
      env {
        name  = "DEMO_USER_1_USERNAME"
        value = var.demo_user_1_username
      }
      env {
        name  = "DEMO_USER_2_USERNAME"
        value = var.demo_user_2_username
      }
      env {
        name  = "JWT_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.jwt_secret.secret_id
            version = "latest"
          }
        }
      }
      env {
        name  = "CSRF_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.csrf_secret.secret_id
            version = "latest"
          }
        }
      }
      env {
        name  = "DEMO_USER_1_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.demo_user_1_password.secret_id
            version = "latest"
          }
        }
      }
      env {
        name  = "DEMO_USER_2_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.demo_user_2_password.secret_id
            version = "latest"
          }
        }
      }
      env {
        name  = "GEMINI_API_KEY"
        value_source {
          secret_key_ref {
            secret  = data.google_secret_manager_secret.gemini_api_key.secret_id
            version = "latest"
          }
        }
      }
      env {
        name  = "NEON_DATABASE_URL"
        value_source {
          secret_key_ref {
            secret  = data.google_secret_manager_secret.neon_db_url.secret_id
            version = "latest"
          }
        }
      }
      env {
        name  = "TELEGRAM_BOT_TOKEN"
        value_source {
          secret_key_ref {
            secret  = data.google_secret_manager_secret.telegram_bot_token.secret_id
            version = "latest"
          }
        }
      }
      env {
        name  = "TELEGRAM_CHAT_ID"
        value_source {
          secret_key_ref {
            secret  = data.google_secret_manager_secret.telegram_chat_id.secret_id
            version = "latest"
          }
        }
      }
    }
  }
}

resource "google_cloud_run_v2_service_iam_member" "public_invoker" {
  location = google_cloud_run_v2_service.app.location
  name     = google_cloud_run_v2_service.app.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# Dominio propio del producto (URL fija de marca). El dominio base tsib.dev esta
# verificado en Search Console; los registros DNS se publican en Squarespace.
resource "google_cloud_run_domain_mapping" "app" {
  name     = "rag-del-pueblo.tsib.dev"
  location = var.region
  metadata {
    namespace = var.project
  }
  spec {
    route_name = google_cloud_run_v2_service.app.name
  }
  lifecycle {
    ignore_changes = [
      metadata[0].labels,
      metadata[0].annotations,
    ]
  }
}
