import { apiClient } from './client'

export interface PipelineStatus {
  status: string
  last_run: string
  last_success: string
  records_count: number
  semaphore: string
}

export interface PipelineLogs {
  lines: string[]
  total_lines: number
}

export interface LayerRun {
  capa: string
  status: string
  run_id: string
  duracion_seg: number | null
  records_in: number
  records_out: number
  dlq_count: number
  started_at: string | null
  finished_at: string | null
}

export interface PipelineLayersResponse {
  layers: LayerRun[]
  health_global: string
  ultima_corrida_global: string
}

export async function getPipelineStatus(): Promise<PipelineStatus> {
  return apiClient<PipelineStatus>('/observability/status')
}

export async function getPipelineLogs(lines = 50): Promise<PipelineLogs> {
  return apiClient<PipelineLogs>(`/observability/logs?lines=${lines}`)
}

export async function getPipelineLayers(): Promise<PipelineLayersResponse> {
  return apiClient<PipelineLayersResponse>('/observability/pipeline/layers')
}

export async function getPipelineLogsByLayer(layer: string, lines = 50): Promise<PipelineLogs> {
  return apiClient<PipelineLogs>(`/observability/pipeline/logs/${layer}?lines=${lines}`)
}
