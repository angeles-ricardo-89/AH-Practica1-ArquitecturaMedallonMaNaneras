terraform {
  required_version = ">= 1.9"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 6.0, < 7.0"
    }
    random = {
      source  = "hashicorp/random"
      version = ">= 3.6"
    }
  }
  backend "gcs" {
    bucket = "rag-conferencias-matutinas-tfstate"
    prefix = "terraform/state"
  }
}
