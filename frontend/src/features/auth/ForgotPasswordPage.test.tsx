import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { apiError, json, mockApi, renderWithProviders } from '@/test/render'

import ForgotPasswordPage from './ForgotPasswordPage'

describe('ForgotPasswordPage', () => {
  it('asks for the phone, then the code and a new password, and confirms', async () => {
    const api = mockApi({
      'POST /api/v1/auth/password-reset/request': () => json({ message: 'If that phone number has an account, a code is on its way by SMS.' }, 202),
      'POST /api/v1/auth/password-reset/confirm': () => json({ message: 'Your password is changed. Sign in with the new one.' }),
    })
    renderWithProviders(<ForgotPasswordPage />, { path: '/forgot-password', pattern: '/forgot-password' })
    await userEvent.type(screen.getByLabelText('Phone number'), '0712 345 678')
    await userEvent.click(screen.getByRole('button', { name: 'Send me a code' }))
    expect(await screen.findByRole('heading', { name: 'Check your SMS' })).toBeInTheDocument()
    expect(api.of('POST', '/api/v1/auth/password-reset/request')[0].body).toEqual({ phone: '0712 345 678' })

    await userEvent.type(screen.getByLabelText('Code from the SMS'), '123456')
    await userEvent.type(screen.getByLabelText('New password'), 'correct horse battery')
    await userEvent.type(screen.getByLabelText('New password again'), 'wrong one')
    await userEvent.click(screen.getByRole('button', { name: 'Change password' }))
    expect(await screen.findByText('The two passwords do not match')).toBeInTheDocument()
    expect(api.of('POST', '/api/v1/auth/password-reset/confirm')).toHaveLength(0)

    await userEvent.clear(screen.getByLabelText('New password again'))
    await userEvent.type(screen.getByLabelText('New password again'), 'correct horse battery')
    await userEvent.click(screen.getByRole('button', { name: 'Change password' }))
    expect(await screen.findByRole('heading', { name: 'Password changed' })).toBeInTheDocument()
    expect(api.of('POST', '/api/v1/auth/password-reset/confirm')[0].body).toEqual({ phone: '0712 345 678', code: '123456', new_password: 'correct horse battery' })
    expect(screen.getByRole('link', { name: 'Sign in' })).toHaveAttribute('href', '/login')
  })

  it('explains when SMS reset is not switched on, and when a code is wrong', async () => {
    mockApi({
      'POST /api/v1/auth/password-reset/request': () => apiError(503, 'PASSWORD_RESET_NOT_CONFIGURED', 'Password reset by SMS is not switched on in this version yet.'),
    })
    renderWithProviders(<ForgotPasswordPage />, { path: '/forgot-password', pattern: '/forgot-password' })
    await userEvent.type(screen.getByLabelText('Phone number'), '0712345678')
    await userEvent.click(screen.getByRole('button', { name: 'Send me a code' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('not switched on in this test version yet')

    mockApi({
      'POST /api/v1/auth/password-reset/request': () => json({ message: 'ok' }, 202),
      'POST /api/v1/auth/password-reset/confirm': () => apiError(400, 'RESET_CODE_INVALID', 'That code is not valid. Ask for a new one.'),
    })
    await userEvent.click(screen.getByRole('button', { name: 'Send me a code' }))
    await screen.findByRole('heading', { name: 'Check your SMS' })
    await userEvent.type(screen.getByLabelText('Code from the SMS'), '999999')
    await userEvent.type(screen.getByLabelText('New password'), 'correct horse battery')
    await userEvent.type(screen.getByLabelText('New password again'), 'correct horse battery')
    await userEvent.click(screen.getByRole('button', { name: 'Change password' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('That code is not valid or has expired')
  })
})
