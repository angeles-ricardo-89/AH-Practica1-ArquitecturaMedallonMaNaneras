output "service_url" {
  description = "URL publica run.app del servicio"
  value       = google_cloud_run_v2_service.app.uri
}

output "service_id" {
  description = "ID completo del servicio Cloud Run"
  value       = google_cloud_run_v2_service.app.id
}

output "demo_user_1_username" {
  value = var.demo_user_1_username
}

output "demo_user_2_username" {
  value = var.demo_user_2_username
}

output "demo_user_1_password" {
  description = "Contrasena demo 1 (solo para el PDF y smoke test)"
  sensitive   = true
  value       = random_password.demo_user_1_password.result
}

output "demo_user_2_password" {
  description = "Contrasena demo 2 (solo para el PDF y smoke test)"
  sensitive   = true
  value       = random_password.demo_user_2_password.result
}
