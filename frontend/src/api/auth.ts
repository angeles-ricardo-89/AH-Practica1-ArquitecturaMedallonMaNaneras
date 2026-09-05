import { apiClient } from './client'

export interface Me {
  id: number
  username: string
  role: string
}

const CSRF_KEY = 'lakehouse_csrf'

export function saveCsrfToken(token: string) {
  sessionStorage.setItem(CSRF_KEY, token)
}

export function getCsrfToken(): string {
  return sessionStorage.getItem(CSRF_KEY) ?? ''
}

export function csrfHeader(): Record<string, string> {
  const token = getCsrfToken()
  return token ? { 'X-CSRF-Token': token } : {}
}

export async function login(username: string, password: string): Promise<Me> {
  const data = await apiClient<{ csrf_token: string }>('/auth/login', {
    method: 'POST',
    body: { username, password },
  })
  saveCsrfToken(data.csrf_token)
  return fetchMe()
}

export async function logout(): Promise<void> {
  try {
    await apiClient<void>('/auth/logout', { method: 'POST', headers: csrfHeader() })
  } finally {
    sessionStorage.removeItem(CSRF_KEY)
  }
}

export async function fetchMe(): Promise<Me> {
  return apiClient<Me>('/auth/me')
}
