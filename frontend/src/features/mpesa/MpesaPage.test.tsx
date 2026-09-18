import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route } from 'react-router'
import { describe, expect, it } from 'vitest'

import { apiError, json, mockApi, renderWithProviders, staffSession } from '@/test/render'

import type { MpesaMessage, Reconciliation } from './api'
import MpesaPage from './MpesaPage'

const summary: Reconciliation = { date: '2026-09-18', received_count: 2, received_total: '1500.00', matched_count: 1, matched_total: '1000.00', unmatched_count: 1, unmatched_total: '500.00', ignored_count: 0, unparsed_count: 0, recorded_in_app: '1000.00' }

function message(overrides: Partial<MpesaMessage> = {}): MpesaMessage {
  return {
    id: 'm1', status: 'UNMATCHED', code: 'RK1TEST001', amount: '500.00', kind: 'POCHI', sender_name: 'JANE TESTER', sender_phone_masked: '0712***456', account_reference: null,
    occurred_at: '2026-09-18T11:15:00Z', raw_text: 'RK1TEST001 Confirmed…', payment_id: null, sale_id: null, credit_transaction_id: null, customer_id: null, matched_at: null, ignored_at: null, ignore_reason: null,
    created_at: '2026-09-18T11:16:00Z',
    candidates: { payments: [{ payment_id: 'p1', sale_id: 's1', amount: '500.00', reference: null, sold_at: '2026-09-18T11:10:00Z' }], customers: [{ customer_id: 'c1', name: 'Amina Njeri', phone: '+254700111456', balance: '900.00' }] },
    ...overrides,
  }
}

const base = { 'GET /api/v1/mpesa/reconciliation': summary }

describe('MpesaPage', () => {
  it('pastes a message, shows the summary and the unmatched row with its actions', async () => {
    const api = mockApi({
      ...base,
      'GET /api/v1/mpesa/messages': [],
      'POST /api/v1/mpesa/messages': () => json(message(), 201),
    })
    renderWithProviders(<MpesaPage />, { path: '/mpesa', pattern: '/mpesa' })
    expect(await screen.findByText('No M-Pesa messages for this day')).toBeInTheDocument()
    expect(screen.getByText('Not recorded').nextElementSibling).toHaveTextContent('KSh 500')
    await userEvent.type(screen.getByLabelText('M-Pesa message'), 'RK1TEST001 Confirmed. You have received Ksh500.00 from JANE TESTER 0712***456 on 18/9/26 at 2:15 PM. New business balance is Ksh1.00.')
    await userEvent.click(screen.getByRole('button', { name: 'Add message' }))
    await waitFor(() => expect(api.of('POST', '/api/v1/mpesa/messages')).toHaveLength(1))
    expect((api.of('POST', '/api/v1/mpesa/messages')[0].body as { text: string }).text).toMatch(/^RK1TEST001/)
    expect(screen.getByLabelText('M-Pesa message')).toHaveValue('')
  })

  it('shows rows with status, offers Record sale / Deni payment / Match / Ignore to the owner, and navigates to a prefilled sale', async () => {
    mockApi({ ...base, 'GET /api/v1/mpesa/messages': [message(), message({ id: 'm2', status: 'MATCHED', code: 'RK1TEST002', amount: '1000.00', sale_id: 's9', candidates: null })] })
    renderWithProviders(<MpesaPage />, { path: '/mpesa', pattern: '/mpesa', extraRoutes: <Route path="/sales/new" element={<h1>Sell page</h1>} /> })
    expect(await screen.findByText('RK1TEST001', { exact: false })).toBeInTheDocument()
    expect(screen.getAllByText('Not recorded')).toHaveLength(2) // summary label + row badge
    expect(screen.getByText('Recorded', { selector: 'span' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'View sale' })).toHaveAttribute('href', '/sales/s9')
    expect(screen.getByRole('button', { name: 'Ignore' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Record sale' }))
    expect(await screen.findByRole('heading', { name: 'Sell page' })).toBeInTheDocument()
  })

  it('records a deni payment from the phone-suffix candidate and surfaces a refusal', async () => {
    const api = mockApi({
      ...base,
      'GET /api/v1/mpesa/messages': [message({ candidates: null })],
      'GET /api/v1/mpesa/messages/m1': message(),
      'GET /api/v1/customers': [],
      'POST /api/v1/mpesa/messages/m1/repayment': () => apiError(409, 'REPAYMENT_EXCEEDS_BALANCE', 'This would take the balance below zero'),
    })
    renderWithProviders(<MpesaPage />, { path: '/mpesa', pattern: '/mpesa' })
    await userEvent.click(await screen.findByRole('button', { name: 'Deni payment' }))
    const dialog = await screen.findByRole('dialog', { name: /Deni payment of KSh 500/ })
    await userEvent.click(within(dialog).getByRole('button', { name: /Amina Njeri/ }))
    await waitFor(() => expect(api.of('POST', '/api/v1/mpesa/messages/m1/repayment')).toHaveLength(1))
    expect(api.of('POST', '/api/v1/mpesa/messages/m1/repayment')[0].body).toEqual({ customer_id: 'c1', allow_overpayment: false })
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('below zero')
  })

  it('matches to a candidate sale', async () => {
    const api = mockApi({ ...base, 'GET /api/v1/mpesa/messages': [message({ candidates: null })], 'GET /api/v1/mpesa/messages/m1': message(), 'POST /api/v1/mpesa/messages/m1/match': () => json(message({ status: 'MATCHED', sale_id: 's1', candidates: null })) })
    renderWithProviders(<MpesaPage />, { path: '/mpesa', pattern: '/mpesa' })
    await userEvent.click(await screen.findByRole('button', { name: 'Match sale' }))
    const dialog = await screen.findByRole('dialog', { name: 'Which sale is this?' })
    await userEvent.click(within(dialog).getByRole('button', { name: /KSh 500/ }))
    await waitFor(() => expect(api.of('POST', '/api/v1/mpesa/messages/m1/match')).toHaveLength(1))
    expect(api.of('POST', '/api/v1/mpesa/messages/m1/match')[0].body).toEqual({ payment_id: 'p1' })
  })

  it('hides Ignore from staff and prefills the box from a shared message', async () => {
    mockApi({ ...base, 'GET /api/v1/mpesa/messages': [message()] })
    renderWithProviders(<MpesaPage />, { session: staffSession, path: '/mpesa?text=RK1TEST009%20Confirmed.%20You%20have%20received', pattern: '/mpesa' })
    expect(await screen.findByRole('button', { name: 'Record sale' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Ignore' })).not.toBeInTheDocument()
    expect(screen.getByLabelText('M-Pesa message')).toHaveValue('RK1TEST009 Confirmed. You have received')
  })
})
