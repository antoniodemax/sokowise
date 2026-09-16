import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { _resetRefreshForTests, ApiError, CSRF_HEADER, refreshSession, request } from './api'
import { sessionStore, type SessionResponse } from './session'

const session: SessionResponse = {
  access_token: 'fresh-token',
  token_type: 'bearer',
  expires_in: 900,
  user: { id: 'u1', full_name: 'Amina', phone: '+254712345678', email: null, must_change_password: false },
  business: { id: 'b1', name: 'Amina Duka', business_type: 'GENERAL_SHOP', currency: 'KES', timezone: 'Africa/Nairobi', is_active: true },
  role: 'OWNER',
}

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const envelope = (status: number, code: string, message = 'nope', details: unknown = null) =>
  json(status, { error: { code, message, details, request_id: 'req-1' } })

let fetchMock: ReturnType<typeof vi.fn>

beforeEach(() => {
  sessionStore.clear()
  _resetRefreshForTests()
  fetchMock = vi.fn()
  vi.stubGlobal('fetch', fetchMock)
})
afterEach(() => vi.unstubAllGlobals())

describe('request', () => {
  it('sends the bearer token, cookies and JSON', async () => {
    sessionStore.set(session)
    fetchMock.mockResolvedValueOnce(json(200, { ok: true }))
    await request('/api/v1/things', { method: 'POST', body: { a: 1 }, query: { q: 'x', skip: undefined } })
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/v1/things?q=x')
    expect(init.credentials).toBe('include')
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer fresh-token')
    expect((init.headers as Record<string, string>)['Content-Type']).toBe('application/json')
    expect(init.body).toBe('{"a":1}')
  })

  it('maps the error envelope to ApiError', async () => {
    fetchMock.mockResolvedValueOnce(envelope(409, 'INSUFFICIENT_STOCK', 'Not enough stock', { product: 'p1' }))
    const error = await request('/api/v1/sales', { method: 'POST', body: {}, auth: false }).catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 409, code: 'INSUFFICIENT_STOCK', message: 'Not enough stock', details: { product: 'p1' }, requestId: 'req-1' })
  })

  it('turns a failed fetch into a NETWORK_ERROR', async () => {
    fetchMock.mockRejectedValueOnce(new TypeError('Failed to fetch'))
    await expect(request('/api/v1/auth/me')).rejects.toMatchObject({ status: 0, code: 'NETWORK_ERROR' })
  })

  it('refreshes once and retries on 401, sending the CSRF header to the refresh endpoint', async () => {
    sessionStore.set({ ...session, access_token: 'stale' })
    fetchMock
      .mockResolvedValueOnce(envelope(401, 'UNAUTHORIZED'))
      .mockResolvedValueOnce(json(200, session))
      .mockResolvedValueOnce(json(200, { me: true }))
    const result = await request<{ me: boolean }>('/api/v1/auth/me')
    expect(result).toEqual({ me: true })
    const calls = fetchMock.mock.calls as [string, RequestInit][]
    expect(calls.map(([url]) => url)).toEqual(['/api/v1/auth/me', '/api/v1/auth/refresh', '/api/v1/auth/me'])
    expect((calls[1][1].headers as Record<string, string>)[CSRF_HEADER]).toBe('sokowise')
    expect((calls[1][1].headers as Record<string, string>).Authorization).toBeUndefined()
    expect((calls[2][1].headers as Record<string, string>).Authorization).toBe('Bearer fresh-token')
    expect(sessionStore.getToken()).toBe('fresh-token')
  })

  it('clears the session and rethrows when the refresh is refused', async () => {
    sessionStore.set({ ...session, access_token: 'stale' })
    fetchMock.mockResolvedValueOnce(envelope(401, 'UNAUTHORIZED')).mockResolvedValueOnce(envelope(401, 'INVALID_REFRESH_TOKEN'))
    await expect(request('/api/v1/auth/me')).rejects.toMatchObject({ status: 401 })
    expect(sessionStore.get()).toBeNull()
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('never refreshes for unauthenticated calls such as login', async () => {
    fetchMock.mockResolvedValueOnce(envelope(401, 'INVALID_CREDENTIALS', 'Invalid phone/email or password'))
    await expect(request('/api/v1/auth/login', { method: 'POST', body: {}, auth: false })).rejects.toMatchObject({ code: 'INVALID_CREDENTIALS' })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})

describe('refreshSession single flight', () => {
  it('shares one refresh between concurrent 401s and retries each request once', async () => {
    sessionStore.set({ ...session, access_token: 'stale' })
    let releaseRefresh!: (value: Response) => void
    const pendingRefresh = new Promise<Response>((resolve) => {
      releaseRefresh = resolve
    })
    fetchMock.mockImplementation((url: string, init: RequestInit) => {
      if (url === '/api/v1/auth/refresh') return pendingRefresh
      const auth = (init.headers as Record<string, string>).Authorization
      return Promise.resolve(auth === 'Bearer fresh-token' ? json(200, { url }) : envelope(401, 'UNAUTHORIZED'))
    })
    const inflight = Promise.all([request('/api/v1/a'), request('/api/v1/b'), request('/api/v1/c')])
    await Promise.resolve()
    await new Promise((r) => setTimeout(r, 0))
    releaseRefresh(json(200, session))
    const results = await inflight
    expect(results).toEqual([{ url: '/api/v1/a' }, { url: '/api/v1/b' }, { url: '/api/v1/c' }])
    const refreshCalls = (fetchMock.mock.calls as [string][]).filter(([url]) => url === '/api/v1/auth/refresh')
    expect(refreshCalls).toHaveLength(1)
  })

  it('returns the same promise to direct callers while a refresh is in flight', async () => {
    fetchMock.mockResolvedValue(json(200, session))
    const [a, b] = await Promise.all([refreshSession(), refreshSession()])
    expect(a).toEqual(b)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})
