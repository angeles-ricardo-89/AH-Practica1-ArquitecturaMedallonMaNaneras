import { apiClient } from './client'

export interface ModelosConfig {
  llm: string
  embedding: string
}

export interface ConfigResponse {
  ambiente: string
  docker: boolean
  version: string
  modelos: ModelosConfig
}

export async function getConfig(): Promise<ConfigResponse> {
  return apiClient<ConfigResponse>('/config')
}
