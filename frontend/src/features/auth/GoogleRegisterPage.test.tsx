import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { describe, expect, it, vi } from 'vitest'

import { AuthContext, type AuthContextValue } from './auth-context'
import GoogleRegisterPage from './GoogleRegisterPage'

function renderPage(state: unknown, overrides: Partial<AuthContextValue> = {}) {
  const value: AuthContextValue = {
    session: null,
    restoring: false,
    login: vi.fn(),
    register: vi.fn(),
    changePassword: vi.fn(),
    signInWithGoogle: vi.fn(),
    registerWithGoogle: vi.fn(),
    logout: vi.fn(),
    logoutAll: vi.fn(),
    ...overrides,
  }
  render(
    <AuthContext.Provider value={value}>
      <MemoryRouter initialEntries={[{ pathname: '/register/google', state }]}>
        <Routes>
          <Route path="/register/google" element={<GoogleRegisterPage />} />
          <Route path="/login" element={<h1>Login page</h1>} />
          <Route path="/dashboard" element={<h1>Dashboard page</h1>} />
        </Routes>
      </MemoryRouter>
    </AuthContext.Provider>,
  )
  return value
}

const pending = { status: 'needs_registration', registration_token: 'tok-0123456789abcdefghij', email: 'amina@example.com', name: 'Amina Wanjiru' }

describe('GoogleRegisterPage', () => {
  it('shows the Google email, prefills the name, and submits the token with phone and business', async () => {
    const value = renderPage(pending, { registerWithGoogle: vi.fn().mockResolvedValue({}) })
    expect(screen.getByText('amina@example.com')).toBeInTheDocument()
    expect(screen.getByLabelText('Your name')).toHaveValue('Amina Wanjiru')
    await userEvent.type(screen.getByLabelText('Phone number'), '0712345678')
    await userEvent.type(screen.getByLabelText('Business name'), 'Amina Duka')
    await userEvent.selectOptions(screen.getByLabelText('Type of business'), 'BOUTIQUE')
    await userEvent.click(screen.getByRole('button', { name: 'Create business' }))
    expect(await screen.findByRole('heading', { name: 'Dashboard page' })).toBeInTheDocument()
    expect(value.registerWithGoogle).toHaveBeenCalledWith({ registration_token: 'tok-0123456789abcdefghij', full_name: 'Amina Wanjiru', phone: '0712345678', business_name: 'Amina Duka', business_type: 'BOUTIQUE' })
  })

  it('sends people without a pending Google sign-in back to the login page', () => {
    renderPage(null)
    expect(screen.getByRole('heading', { name: 'Login page' })).toBeInTheDocument()
  })
})
