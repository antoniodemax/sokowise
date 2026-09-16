import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { expense } from '@/test/fixtures'
import { json, mockApi, renderWithProviders } from '@/test/render'

import ExpensesPage from './ExpensesPage'

describe('ExpensesPage', () => {
  it('lists expenses with a running total, records a new one and soft-deletes after confirmation', async () => {
    const api = mockApi({
      'GET /api/v1/expenses': [expense(), expense({ id: 'e-2', amount: '250.50', category: 'TRANSPORT', payment_method: 'MPESA', reference: 'QX1' })],
      'GET /api/v1/expenses/categories': { suggested: ['RENT', 'TRANSPORT', 'AIRTIME'] },
      'POST /api/v1/expenses': () => json(expense({ id: 'e-3' }), 201),
      'DELETE /api/v1/expenses/e-1': () => json(null, 204),
    })
    renderWithProviders(<ExpensesPage />, { path: '/expenses', pattern: '/expenses' })
    expect(await screen.findByRole('cell', { name: 'TRANSPORT' })).toBeInTheDocument()
    expect(screen.getByText('KSh 1,750.50')).toBeInTheDocument()
    expect(api.of('GET', '/api/v1/expenses')[0].url.searchParams.get('date_from')).toMatch(/^\d{4}-\d{2}-01$/)

    await userEvent.click(screen.getByRole('button', { name: 'Record expense' }))
    const dialog = await screen.findByRole('dialog', { name: 'Record an expense' })
    await userEvent.type(within(dialog).getByLabelText('Amount (KSh)'), '300')
    await userEvent.type(within(dialog).getByLabelText('Category'), 'Airtime')
    await userEvent.selectOptions(within(dialog).getByLabelText('Paid by'), 'MPESA')
    await userEvent.type(within(dialog).getByLabelText(/M-Pesa code/), 'QAB12')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Record expense' }))
    await waitFor(() => expect(api.of('POST', '/api/v1/expenses')).toHaveLength(1))
    expect(api.of('POST', '/api/v1/expenses')[0].body).toMatchObject({ amount: '300', category: 'Airtime', payment_method: 'MPESA', reference: 'QAB12', note: null })
    expect((api.of('POST', '/api/v1/expenses')[0].body as { incurred_at: string }).incurred_at).toMatch(/Z$/)

    await userEvent.click(screen.getByRole('button', { name: 'Delete RENT expense' }))
    const confirm = await screen.findByRole('dialog', { name: 'Delete this expense?' })
    await userEvent.click(within(confirm).getByRole('button', { name: 'Delete' }))
    await waitFor(() => expect(api.of('DELETE', '/api/v1/expenses/e-1')).toHaveLength(1))
  })
})
