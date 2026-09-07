variable "project" {
  type        = string
  description = "Proyecto GCP destino"
}

variable "region" {
  type        = string
  description = "Region de despliegue"
  default     = "us-central1"
}

variable "service_name" {
  type        = string
  description = "Nombre del servicio Cloud Run"
  default     = "rag-del-pueblo"
}

variable "artifact_repo" {
  type        = string
  description = "Nombre del repositorio Artifact Registry (Docker)"
  default     = "lakehouse"
}

variable "image" {
  type        = string
  description = "Imagen del build unico web+API (Artifact Registry)"
}

variable "max_instances" {
  type        = number
  description = "Maximo de instancias Cloud Run (control de costo)"
  default     = 1
}

variable "min_instances" {
  type        = number
  description = "Instancias minimas (0 = escala a cero)"
  default     = 0
}

variable "cpu" {
  type    = string
  default = "1"
}

variable "memory" {
  type    = string
  default = "1Gi"
}

variable "concurrency" {
  type    = number
  default = 10
}

variable "demo_user_1_username" {
  type        = string
  description = "Usuario demo 1 (se entrega solo en el PDF)"
}

variable "demo_user_2_username" {
  type        = string
  description = "Usuario demo 2 (se entrega solo en el PDF)"
}

variable "existing_secrets" {
  type = object({
    gemini_api_key     = string
    neon_db_url        = string
    telegram_bot_token = string
    telegram_chat_id   = string
  })
  description = "Nombres de secretos existentes en Secret Manager"
}
