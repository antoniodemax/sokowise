import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { customer, ledgerEntry, UUID_RE } from '@/test/fixtures'
import { apiError, json, mockApi, renderWithProviders, staffSession } from '@/test/render'

import CustomerDetailPage from './CustomerDetailPage'

const ledger = { customer_id: 'c-amina', balance: '100.00', credit_limit: '120.00', entries: [ledgerEntry()] }

describe('CustomerDetailPage', () => {
  it('records a repayment with an idempotency key and handles overpayment', async () => {
    let attempts = 0
    const api = mockApi({
      'GET /api/v1/customers/c-amina': customer(),
      'GET /api/v1/customers/c-amina/ledger': ledger,
      'POST /api/v1/customers/c-amina/repayments': () =>
        ++attempts === 1 ? apiError(409, 'REPAYMENT_EXCEEDS_BALANCE', 'Repayment exceeds balance') : json(ledgerEntry({ entry_type: 'REPAYMENT', amount: '-150.00', balance_after: '-50.00' }), 201),
    })
    renderWithProviders(<CustomerDetailPage />, { path: '/customers/c-amina', pattern: '/customers/:customerId' })
    expect(await screen.findByText('Owes you')).toBeInTheDocument()
    expect(screen.getByText('Credit sale')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Adjust balance' })).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Record repayment' }))
    const dialog = await screen.findByRole('dialog', { name: 'Record a repayment' })
    await userEvent.type(within(dialog).getByLabelText('Amount (KSh)'), '150')
    await userEvent.selectOptions(within(dialog).getByLabelText('Paid by'), 'MPESA')
    await userEvent.type(within(dialog).getByLabelText(/M-Pesa code/), 'ABC123')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Record repayment' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('more than the KSh 100 owed')
    await userEvent.click(within(dialog).getByLabelText('The customer is paying extra in advance'))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Record repayment' }))
    await waitFor(() => expect(api.of('POST', '/api/v1/customers/c-amina/repayments')).toHaveLength(2))

    const [first, second] = api.of('POST', '/api/v1/customers/c-amina/repayments')
    expect(first.body).toEqual({ amount: '150', payment_method: 'MPESA', reference: 'ABC123', allow_overpayment: false })
    expect(second.body).toMatchObject({ allow_overpayment: true })
    expect(first.headers['Idempotency-Key']).toMatch(UUID_RE)
    expect(second.headers['Idempotency-Key']).not.toBe(first.headers['Idempotency-Key'])
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('hides balance adjustments from staff', async () => {
    mockApi({ 'GET /api/v1/customers/c-amina': customer(), 'GET /api/v1/customers/c-amina/ledger': ledger })
    renderWithProviders(<CustomerDetailPage />, { session: staffSession, path: '/customers/c-amina', pattern: '/customers/:customerId' })
    expect(await screen.findByRole('button', { name: 'Record repayment' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Adjust balance' })).not.toBeInTheDocument()
  })
})
