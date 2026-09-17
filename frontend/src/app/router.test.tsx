import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { AuthContext, type AuthContextValue } from '@/features/auth/auth-context'
import { sessionStore, type Session, type SessionResponse } from '@/lib/session'
import { ownerSession } from '@/test/render'

import { AppProviders } from './providers'
import { AppRouter } from './router'

vi.mock('@/features/auth/AuthContext', () => ({ AuthProvider: ({ children }: { children: React.ReactNode }) => children }))

function renderAt(path: string, session: Session | null) {
  window.history.pushState({}, '', path)
  const summary = { period: { timezone: 'Africa/Nairobi', date_from: '2026-09-16', date_to: '2026-09-16' }, sales_count: 0, revenue: '0.00', discounts: '0.00', cogs: '0.00', lines_missing_cost: 0, products_missing_cost: 0, gross_profit: '0.00', expenses: '0.00', net_profit: '0.00', tender_split: {}, cash_collected: {}, cash_collected_total: '0.00', receivables_outstanding: '0.00' }
  vi.stubGlobal('fetch', vi.fn(async (input: string | URL) => new Response(JSON.stringify(String(input).includes('/analytics/summary') ? summary : []), { status: 200, headers: { 'Content-Type': 'application/json' } })))
  if (session) sessionStore.set({ access_token: 't', token_type: 'bearer', expires_in: 900, ...session } as SessionResponse)
  else sessionStore.clear()
  const auth: AuthContextValue = { session, restoring: false, login: vi.fn(), register: vi.fn(), changePassword: vi.fn(), logout: vi.fn(), logoutAll: vi.fn() }
  return render(
    <AppProviders>
      <AuthContext.Provider value={auth}>
        <AppRouter />
      </AuthContext.Provider>
    </AppProviders>,
  )
}

describe('AppRouter', () => {
  it('serves the public homepage at / without a session', async () => {
    renderAt('/', null)
    expect(await screen.findByRole('heading', { level: 1 })).toHaveTextContent('Know your business')
    expect(screen.getAllByRole('link', { name: 'Sign in' })[0]).toHaveAttribute('href', '/login')
  })

  it('keeps /dashboard and the other app routes behind login', async () => {
    renderAt('/dashboard', null)
    expect(await screen.findByRole('heading', { name: /sign in/i })).toBeInTheDocument()
    expect(window.location.pathname).toBe('/login')
  })

  it('keeps the copilot behind login and, for staff, behind the owner role', async () => {
    renderAt('/assistant', null)
    expect(await screen.findByRole('heading', { name: /sign in/i })).toBeInTheDocument()
    expect(window.location.pathname).toBe('/login')
    renderAt('/assistant', { ...ownerSession, role: 'STAFF' })
    expect(await screen.findByText('Owners only')).toBeInTheDocument()
  })

  it('protects a feature route too', async () => {
    renderAt('/sales', null)
    expect(await screen.findByRole('heading', { name: /sign in/i })).toBeInTheDocument()
    expect(window.location.pathname).toBe('/login')
  })

  it('shows the dashboard to a signed-in owner at /dashboard and sends them there from /login', async () => {
    renderAt('/dashboard', ownerSession)
    expect(await screen.findByRole('heading', { level: 1, name: /Hello, Amina/ })).toBeInTheDocument()
    window.history.pushState({}, '', '/login')
    renderAt('/login', ownerSession)
    expect(await screen.findAllByRole('heading', { level: 1, name: /Hello, Amina/ })).not.toHaveLength(0)
    expect(window.location.pathname).toBe('/dashboard')
  })
})
