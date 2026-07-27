import { apiClient } from './client'

export interface SourceChunk {
  conference_date: string
  participant: string
  chunk_text: string
  similarity: number
}

export interface ChatResponse {
  answer: string
  sources: SourceChunk[]
  token_usage: Record<string, number>
}

export async function sendChatMessage(query: string, top_k = 8): Promise<ChatResponse> {
  return apiClient<ChatResponse>('/chat/', {
    method: 'POST',
    body: { query, top_k },
  })
}
