/**
 * Typed fetch wrapper for the SokoWise API (docs/ARCHITECTURE.md §4, §5.1).
 *
 * - Base URL from VITE_API_BASE_URL; empty in local dev (Vite proxies /api).
 * - Sends the access token as a bearer header and cookies with every request.
 * - Maps the backend error envelope to ApiError; network failures become
 *   ApiError(status 0, NETWORK_ERROR).
 * - On 401 for an authenticated request it refreshes the session once — through a
 *   single in-flight refresh shared by every caller — and retries the request. A
 *   second refresh for the same token would be treated as token reuse by the
 *   backend and would end the session for everyone.
 */

import type { ErrorEnvelope } from '@/types/api'

import { sessionStore, type SessionResponse } from './session'

export const API_BASE_URL: string = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, '') ?? ''
export const CSRF_HEADER = 'X-Requested-With'
export const CSRF_VALUE = 'sokowise'
const REFRESH_PATH = '/api/v1/auth/refresh'

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: unknown
  readonly requestId: string | null

  constructor(status: number, code: string, message: string, details: unknown = null, requestId: string | null = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
    this.requestId = requestId
  }

  static network(): ApiError {
    return new ApiError(0, 'NETWORK_ERROR', 'Could not reach SokoWise. Check your connection and try again.')
  }
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'
  body?: unknown
  /** Attach the bearer token and refresh on 401 (default true). */
  auth?: boolean
  /** Add the CSRF header required by the cookie-authenticated auth endpoints. */
  csrf?: boolean
  headers?: Record<string, string>
  query?: Record<string, string | number | boolean | null | undefined>
  signal?: AbortSignal
}

function buildUrl(path: string, query?: RequestOptions['query']): string {
  const url = `${API_BASE_URL}${path}`
  if (!query) return url
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== '') params.set(key, String(value))
  }
  const qs = params.toString()
  return qs ? `${url}?${qs}` : url
}

async function toApiError(response: Response): Promise<ApiError> {
  const envelope = await response.json().then((body: ErrorEnvelope) => body).catch(() => null)
  const error = envelope?.error
  if (error && typeof error.code === 'string') {
    return new ApiError(response.status, error.code, error.message, error.details, error.request_id)
  }
  return new ApiError(response.status, 'HTTP_ERROR', response.statusText || 'Request failed')
}

async function send(path: string, options: RequestOptions): Promise<Response> {
  const headers: Record<string, string> = { Accept: 'application/json', ...options.headers }
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'
  if (options.csrf) headers[CSRF_HEADER] = CSRF_VALUE
  const token = sessionStore.getToken()
  if (options.auth !== false && token) headers.Authorization = `Bearer ${token}`
  try {
    return await fetch(buildUrl(path, options.query), {
      method: options.method ?? 'GET',
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      credentials: 'include',
      signal: options.signal,
    })
  } catch {
    throw ApiError.network()
  }
}

async function parse<T>(response: Response): Promise<T> {
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

/** Perform a request; on 401 with a session, refresh once (single-flight) and retry. */
export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  let response = await send(path, options)
  if (response.status === 401 && options.auth !== false && path !== REFRESH_PATH) {
    const refreshed = await refreshSession()
    if (refreshed === null) throw await toApiError(response)
    response = await send(path, options)
  }
  if (!response.ok) throw await toApiError(response)
  return parse<T>(response)
}

let inflightRefresh: Promise<SessionResponse | null> | null = null

/**
 * Rotate the refresh cookie and get a new access token. Concurrent callers share
 * one request. Returns null (and clears the session) when the backend refuses —
 * no cookie, expired, or revoked.
 */
export function refreshSession(): Promise<SessionResponse | null> {
  if (inflightRefresh) return inflightRefresh
  inflightRefresh = (async () => {
    try {
      const response = await send(REFRESH_PATH, { method: 'POST', auth: false, csrf: true })
      if (!response.ok) {
        sessionStore.clear()
        return null
      }
      const session = (await response.json()) as SessionResponse
      sessionStore.set(session)
      return session
    } catch {
      // Network failure: keep whatever session state we had; the caller sees the error.
      return null
    } finally {
      inflightRefresh = null
    }
  })()
  return inflightRefresh
}

/** For tests: forget an in-flight refresh. */
export function _resetRefreshForTests(): void {
  inflightRefresh = null
}
