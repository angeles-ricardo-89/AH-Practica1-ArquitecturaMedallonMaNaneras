import { apiClient } from './client'
import { csrfHeader } from './auth'
import type { SourceChunk } from './chat'

export interface ConversationSummary {
  id: string
  title: string
  created_at: string
  last_activity_at: string
}

export interface ConversationMessage {
  role: string
  content: string
  created_at: string
}

export interface ConversationDetail {
  id: string
  title: string
  messages: ConversationMessage[]
}

export interface ToolTrace {
  tool_name: string
  arguments: Record<string, unknown>
  result_count: number
  duration_ms: number
  status: string
}

export interface AgentResponse {
  id: string
  answer: string
  refusal: boolean
  model_used: string
  tool_executions: ToolTrace[]
  sources: SourceChunk[]
  token_usage: Record<string, number>
  latency_ms: number
}

export async function listConversations(): Promise<ConversationSummary[]> {
  const data = await apiClient<{ conversations: ConversationSummary[] }>('/conversations/')
  return data.conversations
}

export async function createConversation(title: string): Promise<string> {
  const data = await apiClient<{ id: string }>('/conversations/', {
    method: 'POST',
    body: { title },
    headers: csrfHeader(),
  })
  return data.id
}

export async function getConversation(id: string): Promise<ConversationDetail> {
  return apiClient<ConversationDetail>(`/conversations/${id}`)
}

export async function deleteConversation(id: string): Promise<void> {
  await apiClient<void>(`/conversations/${id}`, {
    method: 'DELETE',
    headers: csrfHeader(),
  })
}

export async function sendAgentMessage(id: string, question: string): Promise<AgentResponse> {
  return apiClient<AgentResponse>(`/conversations/${id}/messages`, {
    method: 'POST',
    body: { question },
    headers: csrfHeader(),
  })
}
