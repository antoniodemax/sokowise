import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { describe, expect, it, vi } from 'vitest'

import { AuthContext, type AuthContextValue } from '@/features/auth/auth-context'
import type { Session } from '@/lib/session'

import { RedirectIfAuthenticated, RequireAuth, RequireOwner } from './guards'

const owner: Session = {
  user: { id: 'u1', full_name: 'Amina', phone: '+254712345678', email: null, must_change_password: false },
  business: { id: 'b1', name: 'Amina Duka', business_type: 'GENERAL_SHOP', currency: 'KES', timezone: 'Africa/Nairobi', is_active: true },
  role: 'OWNER',
  is_platform_admin: false,
}

function renderAt(path: string, session: Session | null, restoring = false) {
  const value: AuthContextValue = { session, restoring, login: vi.fn(), register: vi.fn(), changePassword: vi.fn(), signInWithGoogle: vi.fn(), registerWithGoogle: vi.fn(), logout: vi.fn(), logoutAll: vi.fn() }
  render(
    <AuthContext.Provider value={value}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route element={<RedirectIfAuthenticated />}>
            <Route path="/login" element={<p>login page</p>} />
          </Route>
          <Route element={<RequireAuth />}>
            <Route path="/change-password" element={<p>change password page</p>} />
            <Route path="/dashboard" element={<p>dashboard page</p>} />
            <Route element={<RequireOwner />}>
              <Route path="/expenses" element={<p>expenses page</p>} />
            </Route>
          </Route>
        </Routes>
      </MemoryRouter>
    </AuthContext.Provider>,
  )
}

describe('route guards', () => {
  it('sends anonymous visitors to the login page', () => {
    renderAt('/dashboard', null)
    expect(screen.getByText('login page')).toBeInTheDocument()
  })
  it('shows a restoring state before the first refresh settles', () => {
    renderAt('/dashboard', null, true)
    expect(screen.getByRole('status')).toHaveTextContent('Restoring your session')
  })
  it('lets a signed-in owner through and keeps them off the login page', () => {
    renderAt('/dashboard', owner)
    expect(screen.getByText('dashboard page')).toBeInTheDocument()
  })
  it('redirects signed-in users away from login', () => {
    renderAt('/login', owner)
    expect(screen.getByText('dashboard page')).toBeInTheDocument()
  })
  it('forces the password-change screen while must_change_password is set', () => {
    renderAt('/dashboard', { ...owner, user: { ...owner.user, must_change_password: true } })
    expect(screen.getByText('change password page')).toBeInTheDocument()
  })
  it('keeps staff out of owner-only sections without a backend round trip', () => {
    renderAt('/expenses', { ...owner, role: 'STAFF' })
    expect(screen.getByText('Owners only')).toBeInTheDocument()
    renderAt('/expenses', owner)
    expect(screen.getByText('expenses page')).toBeInTheDocument()
  })
})
