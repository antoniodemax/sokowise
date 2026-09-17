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

  static timeout(): ApiError {
    return new ApiError(0, 'TIMEOUT', 'SokoWise is taking too long to respond. Check your connection and try again.')
  }

  static badResponse(status: number): ApiError {
    return new ApiError(status, 'BAD_RESPONSE', 'The server sent an unexpected reply. Please try again.')
  }
}

/** Default per-request deadline; a hung connection must never leave a screen spinning forever. */
export const DEFAULT_TIMEOUT_MS = 20_000

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
  /** Deadline for this call (default DEFAULT_TIMEOUT_MS); longer for AI and receipt reads. */
  timeoutMs?: number
}

/**
 * A signal that aborts after `timeoutMs` (reason: TimeoutError) or when `signal` aborts.
 * Built by hand rather than with AbortSignal.timeout/any so it behaves the same in every
 * browser the pilot may use; `release()` stops the timer once the response has arrived.
 */
export function withDeadline(signal: AbortSignal | undefined, timeoutMs: number): { signal: AbortSignal; release: () => void; timedOut: () => boolean } {
  const controller = new AbortController()
  let timedOut = false
  const timer = setTimeout(() => {
    timedOut = true
    controller.abort(new DOMException('Request timed out', 'TimeoutError'))
  }, timeoutMs)
  const forward = () => controller.abort(signal?.reason as unknown)
  if (signal?.aborted) forward()
  else signal?.addEventListener('abort', forward, { once: true })
  return {
    signal: controller.signal,
    release: () => {
      clearTimeout(timer)
      signal?.removeEventListener('abort', forward)
    },
    timedOut: () => timedOut,
  }
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
  const deadline = withDeadline(options.signal, options.timeoutMs ?? DEFAULT_TIMEOUT_MS)
  try {
    return await fetch(buildUrl(path, options.query), {
      method: options.method ?? 'GET',
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      credentials: 'include',
      signal: deadline.signal,
    })
  } catch (error) {
    if (options.signal?.aborted) throw error // the caller cancelled; not a failure to report
    if (deadline.timedOut()) throw ApiError.timeout()
    throw ApiError.network()
  } finally {
    deadline.release()
  }
}

async function parse<T>(response: Response): Promise<T> {
  if (response.status === 204) return undefined as T
  try {
    return (await response.json()) as T
  } catch {
    // A proxy serving HTML for /api (misrouted deploy) must not surface a JSON parser message.
    throw ApiError.badResponse(response.status)
  }
}

/** Perform a request; on 401 with a session, refresh once (single-flight) and retry. */
export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  let response = await send(path, options)
  if (response.status === 401 && options.auth !== false && path !== REFRESH_PATH) {
    const refreshed = await refreshSession()
    if (refreshed === null) {
      // A refused refresh clears the session; if one survives, the refresh itself failed
      // to reach the server, and that is what the user should be told.
      throw sessionStore.get() ? ApiError.network() : await toApiError(response)
    }
    response = await send(path, options)
  }
  if (!response.ok) {
    const error = await toApiError(response)
    if (error.status === 403 && error.code === 'PASSWORD_CHANGE_REQUIRED' && options.auth !== false) {
      // Re-adopt the session so `must_change_password` is current and RequireAuth redirects.
      await refreshSession()
    }
    throw error
  }
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
