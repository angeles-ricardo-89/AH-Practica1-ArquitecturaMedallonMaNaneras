import { apiClient } from './client'

export interface SourceChunk {
  conference_id: string
  conference_date: string
  participant: string
  chunk_text: string
  similarity: number
  conference_url: string
  pregunta_activa: string
  qualitative_label: string
  embedding_3d: number[] | null
}

export interface ChatResponse {
  answer: string
  sources: SourceChunk[]
  token_usage: Record<string, number>
  model_used: string
  latency_ms: number
}

export async function sendChatMessage(query: string, top_k = 8): Promise<ChatResponse> {
  return apiClient<ChatResponse>('/chat/', {
    method: 'POST',
    body: { query, top_k },
  })
}
