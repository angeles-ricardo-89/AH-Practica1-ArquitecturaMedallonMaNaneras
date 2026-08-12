import { apiClient } from './client'

export interface ClusterInfo {
  cluster_id: number
  label: string | null
  chunk_count: number
  avg_membership: number
  sample_chunk_keys: string[]
}

export interface ClusterPoint {
  chunk_key: string
  cluster_id: number
  pertenencia: number
  x: number
  y: number
  z: number
}

export interface ClusterDataResponse {
  run_id: string
  status: string
  cluster_count: number
  noise_count: number
  clusters: ClusterInfo[]
  points: ClusterPoint[]
}

export async function getClustersLatest(): Promise<ClusterDataResponse> {
  return apiClient<ClusterDataResponse>('/clusters/latest')
}

export async function getClustersByRun(runId: string): Promise<ClusterDataResponse> {
  return apiClient<ClusterDataResponse>(`/clusters/${runId}`)
}
