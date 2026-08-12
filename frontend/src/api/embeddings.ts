import { apiClient } from './client'

export interface Embedding3DPoint {
  chunk_key: string
  x: number
  y: number
  z: number
  conference_date: string
  cluster_id?: number
}

export interface Embedding3DResponse {
  points: Embedding3DPoint[]
}

export async function getEmbeddings3D(): Promise<Embedding3DResponse> {
  return apiClient<Embedding3DResponse>('/embeddings/3d')
}
