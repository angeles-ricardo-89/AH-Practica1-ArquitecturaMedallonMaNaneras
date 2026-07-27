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

export async function getPipelineStatus(): Promise<PipelineStatus> {
  return apiClient<PipelineStatus>('/observability/status')
}

export async function getPipelineLogs(lines = 50): Promise<PipelineLogs> {
  return apiClient<PipelineLogs>(`/observability/logs?lines=${lines}`)
}
