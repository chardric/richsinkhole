// Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
// All rights reserved.

const SERVER_URL_KEY = 'rs_server_url'
const TOKEN_KEY = 'rs_token'

export function getServerUrl(): string {
  return localStorage.getItem(SERVER_URL_KEY) || ''
}

export function setServerUrl(url: string): void {
  // Normalize: trim trailing slash
  localStorage.setItem(SERVER_URL_KEY, url.replace(/\/+$/, ''))
}

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) || ''
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearAuth(): void {
  localStorage.removeItem(SERVER_URL_KEY)
  localStorage.removeItem(TOKEN_KEY)
}

export function isSetup(): boolean {
  return !!(getServerUrl() && getToken())
}

export class ApiError extends Error {
  status: number
  detail: string

  constructor(status: number, detail: string) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

export async function api<T>(
  method: string,
  path: string,
  body?: unknown,
  customServer?: string
): Promise<T> {
  const server = customServer ?? getServerUrl()
  const token = getToken()

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  }

  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }

  const url = `${server}${path.startsWith('/') ? path : '/' + path}`

  const res = await fetch(url, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })

  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const errData = await res.json()
      detail = errData.detail || errData.message || detail
    } catch {
      // ignore parse error
    }
    throw new ApiError(res.status, detail)
  }

  // Handle 204 No Content
  if (res.status === 204) return undefined as T

  return res.json() as Promise<T>
}

export const apiGet  = <T>(path: string) => api<T>('GET',    path)
export const apiPost = <T>(path: string, body?: unknown) => api<T>('POST',   path, body)
export const apiPatch = <T>(path: string, body?: unknown) => api<T>('PATCH',  path, body)
export const apiDelete = <T>(path: string) => api<T>('DELETE', path)

export async function login(serverUrl: string, password: string): Promise<void> {
  const normalizedUrl = serverUrl.replace(/\/+$/, '')

  const res = await fetch(`${normalizedUrl}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ password }),
  })

  if (!res.ok) {
    let detail = 'Invalid password or server error'
    try {
      const data = await res.json()
      detail = data.detail || data.message || detail
    } catch {
      // ignore
    }
    throw new ApiError(res.status, detail)
  }

  const data = await res.json()
  if (!data.token) {
    throw new ApiError(200, 'Server did not return a token')
  }

  setServerUrl(normalizedUrl)
  setToken(data.token)
}

export function logout(): void {
  clearAuth()
}
