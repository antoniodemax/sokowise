import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'

import { AuthContext, type AuthContextValue } from './auth-context'
import LoginPage from './LoginPage'
import { ApiError } from '@/lib/api'

function renderLogin(overrides: Partial<AuthContextValue> = {}) {
  const value: AuthContextValue = {
    session: null,
    restoring: false,
    login: vi.fn(),
    register: vi.fn(),
    changePassword: vi.fn(),
    logout: vi.fn(),
    logoutAll: vi.fn(),
    ...overrides,
  }
  render(
    <AuthContext.Provider value={value}>
      <MemoryRouter initialEntries={['/login']}>
        <LoginPage />
      </MemoryRouter>
    </AuthContext.Provider>,
  )
  return value
}

describe('LoginPage', () => {
  it('validates before calling the API', async () => {
    const value = renderLogin()
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText('Enter your phone number or email')).toBeInTheDocument()
    expect(screen.getByText('Enter your password')).toBeInTheDocument()
    expect(value.login).not.toHaveBeenCalled()
  })

  it('submits trimmed credentials', async () => {
    const value = renderLogin({ login: vi.fn().mockResolvedValue({ user: { must_change_password: false } }) })
    await userEvent.type(screen.getByLabelText('Phone number or email'), '  0712 345 678 ')
    await userEvent.type(screen.getByLabelText('Password'), 'correct horse')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    await waitFor(() => expect(value.login).toHaveBeenCalledWith({ identifier: '0712 345 678', password: 'correct horse' }))
  })

  it('explains a rejected origin instead of a generic permission error', async () => {
    const login = vi.fn().mockRejectedValueOnce(new ApiError(403, 'CSRF_REJECTED', 'Request origin is not allowed'))
    renderLogin({ login })
    await userEvent.type(screen.getByLabelText('Phone number or email'), '0712345678')
    await userEvent.type(screen.getByLabelText('Password'), 'correct horse')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/app origin is allowed \(CORS_ORIGINS\)/)
  })

  it('shows the backend message for bad credentials and a friendly one for rate limits', async () => {
    const login = vi
      .fn()
      .mockRejectedValueOnce(new ApiError(401, 'INVALID_CREDENTIALS', 'Invalid phone/email or password'))
      .mockRejectedValueOnce(new ApiError(429, 'RATE_LIMITED', 'Too many attempts; try again shortly'))
    renderLogin({ login })
    await userEvent.type(screen.getByLabelText('Phone number or email'), '0712345678')
    await userEvent.type(screen.getByLabelText('Password'), 'wrong')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid phone/email or password')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Too many attempts')
  })
})
