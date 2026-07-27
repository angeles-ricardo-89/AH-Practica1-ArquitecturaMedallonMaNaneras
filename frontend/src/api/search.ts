import { apiClient } from './client'

export interface SearchRequest {
  query: string
  top_k?: number
  strategy?: 'hnsw' | 'relational_then_vector' | 'hybrid'
  filters?: Record<string, string> | null
}

export interface SearchResponse {
  results: Record<string, unknown>[]
  total: number
  strategy: string
}

export async function searchDocuments(params: SearchRequest): Promise<SearchResponse> {
  return apiClient<SearchResponse>('/search/', {
    method: 'POST',
    body: params,
  })
}
