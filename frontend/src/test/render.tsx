import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, type RenderOptions } from '@testing-library/react'
import type { ReactElement, ReactNode } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { vi } from 'vitest'

import { AuthContext, type AuthContextValue } from '@/features/auth/auth-context'
import { sessionStore, type Session, type SessionResponse } from '@/lib/session'

export const ownerSession: Session = {
  user: { id: 'u-owner', full_name: 'Amina Wanjiru', phone: '+254712345678', email: null, must_change_password: false },
  business: { id: 'b1', name: 'Amina Duka', business_type: 'GENERAL_SHOP', currency: 'KES', timezone: 'Africa/Nairobi', is_active: true },
  role: 'OWNER',
}
export const staffSession: Session = { ...ownerSession, user: { ...ownerSession.user, id: 'u-staff', full_name: 'Brian Staff' }, role: 'STAFF' }

/** Render inside providers with a fixed session; `path` mounts `ui` at `pattern`. */
export function renderWithProviders(
  ui: ReactElement,
  { session = ownerSession, path = '/', pattern = '/', extraRoutes, ...options }: RenderOptions & { session?: Session; path?: string; pattern?: string; extraRoutes?: ReactNode } = {},
) {
  sessionStore.set({ access_token: 'token', token_type: 'bearer', expires_in: 900, ...session } as SessionResponse)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } } })
  const auth: AuthContextValue = { session, restoring: false, login: vi.fn(), register: vi.fn(), changePassword: vi.fn(), logout: vi.fn(), logoutAll: vi.fn() }
  return render(
    <QueryClientProvider client={client}>
      <AuthContext.Provider value={auth}>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path={pattern} element={ui} />
            {extraRoutes}
          </Routes>
        </MemoryRouter>
      </AuthContext.Provider>
    </QueryClientProvider>,
    options,
  )
}

type Handler = (init: RequestInit, url: URL) => Response | Promise<Response>

export function json(body: unknown, status = 200): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

export function apiError(status: number, code: string, message = code, details: unknown = null): Response {
  return json({ error: { code, message, details, request_id: 'req-test' } }, status)
}

/**
 * A fetch stub keyed by "METHOD /path" (query string ignored). Handlers receive the
 * request init and the parsed URL; unmatched calls fail loudly.
 */
export function mockApi(routes: Record<string, Handler | unknown>) {
  const calls: { method: string; url: URL; body: unknown; headers: Record<string, string> }[] = []
  const fetchMock = vi.fn(async (input: string | URL, init: RequestInit = {}) => {
    const url = new URL(String(input), 'http://localhost')
    const method = (init.method ?? 'GET').toUpperCase()
    const headers = (init.headers ?? {}) as Record<string, string>
    const body = typeof init.body === 'string' ? JSON.parse(init.body) : undefined
    calls.push({ method, url, body, headers })
    const handler = routes[`${method} ${url.pathname}`]
    if (handler === undefined) return apiError(404, 'NOT_FOUND', `unmocked ${method} ${url.pathname}`)
    if (typeof handler === 'function') return (handler as Handler)(init, url)
    return json(handler)
  })
  vi.stubGlobal('fetch', fetchMock)
  return { calls, fetchMock, of: (method: string, path: string) => calls.filter((c) => c.method === method && c.url.pathname === path) }
}
