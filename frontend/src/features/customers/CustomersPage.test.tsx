import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { customer } from '@/test/fixtures'
import { apiError, mockApi, renderWithProviders } from '@/test/render'

import CustomersPage from './CustomersPage'

describe('CustomersPage', () => {
  it('lists customers, switches to debtors, and surfaces a duplicate phone on the field', async () => {
    const api = mockApi({
      'GET /api/v1/customers': [customer(), customer({ id: 'c-2', name: 'Brian Otieno', balance: '0.00', phone: null })],
      'GET /api/v1/debtors': [{ customer_id: 'c-amina', name: 'Amina Njeri', phone: '+254711000111', balance: '100.00', credit_limit: '120.00', oldest_unpaid_charge_at: '2026-09-10T08:30:00Z' }],
      'POST /api/v1/customers': () => apiError(409, 'CUSTOMER_PHONE_EXISTS', 'phone exists'),
    })
    renderWithProviders(<CustomersPage />, { path: '/customers', pattern: '/customers' })
    expect(await screen.findByText('Brian Otieno')).toBeInTheDocument()
    expect(screen.getByText('Owes KSh 100')).toBeInTheDocument()
    expect(screen.getByText('Nothing owed')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Export CSV' })).toBeInTheDocument()

    await userEvent.click(screen.getByRole('tab', { name: 'Who owes you' }))
    expect(await screen.findByLabelText('Sort debtors')).toBeInTheDocument()
    expect(await screen.findByText('Amina Njeri')).toBeInTheDocument()
    expect(screen.queryByText('Brian Otieno')).not.toBeInTheDocument()
    expect(api.of('GET', '/api/v1/debtors')[0].url.searchParams.get('sort')).toBe('balance')

    await userEvent.click(screen.getByRole('button', { name: 'Add customer' }))
    const dialog = await screen.findByRole('dialog', { name: 'Add a customer' })
    await userEvent.type(within(dialog).getByLabelText('Name'), 'Amina Njeri')
    await userEvent.type(within(dialog).getByLabelText(/^Phone/), '0711000111')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Add customer' }))
    await waitFor(() => expect(api.of('POST', '/api/v1/customers')).toHaveLength(1))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('phone number already exists')
  })
})
