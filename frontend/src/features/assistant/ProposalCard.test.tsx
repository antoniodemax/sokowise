import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { apiError, json, mockApi, renderWithProviders } from '@/test/render'

import AssistantPage from './AssistantPage'

const quota = { daily_limit: 10, daily_used: 3, monthly_limit: 100, monthly_used: 12, resets_at: '2026-09-17T21:00:00Z' }
const userMsg = { id: 'm1', role: 'user', content: 'Add sukari 1kg at 160', tool_calls: null, stop_reason: null, created_at: '2026-09-17T08:00:00Z' }
const productProposal = {
  id: 'm2',
  role: 'assistant',
  content: 'Sukari 1kg at KSh 160. Tap Confirm to add it.',
  tool_calls: [
    { name: 'search_products', input: { query: 'sukari', limit: 5 }, ok: true, duration_ms: 4 },
    { name: 'propose_product', input: { name: 'Sukari 1kg', selling_price: '160.00' }, ok: true, duration_ms: 0 },
  ],
  stop_reason: 'tool_use',
  created_at: '2026-09-17T08:00:04Z',
  proposal: {
    kind: 'product',
    payload: { name: 'Sukari 1kg', selling_price: '160.00', cost_price: null, unit: 'piece', track_inventory: true, opening_stock: null },
    status: 'PENDING',
    entity_id: null,
    applied_at: null,
  },
}
const conversation = (messages: unknown[]) => ({ id: 'c1', title: 'Add product', created_at: '', updated_at: '', messages })
const base = { 'GET /api/v1/ai/quota': quota, 'GET /api/v1/ai/conversations': [{ id: 'c1', title: 'Add product', created_at: '', updated_at: '' }] }

describe('ProposalCard', () => {
  it('shows the proposal as editable fields and sends the edited payload on Confirm, then locks the card', async () => {
    const api = mockApi({
      ...base,
      'GET /api/v1/ai/conversations/c1': conversation([userMsg, productProposal]),
      'POST /api/v1/ai/conversations/c1/messages/m2/confirm': (init: RequestInit) => {
        const body = JSON.parse(String(init.body)) as { payload: Record<string, unknown> }
        return json({
          message: { ...productProposal, proposal: { ...productProposal.proposal, payload: body.payload, status: 'APPLIED', entity_id: 'p9', applied_at: '2026-09-17T08:01:00Z' } },
          kind: 'product',
          entity_id: 'p9',
        })
      },
    })
    renderWithProviders(<AssistantPage />, { path: '/assistant?c=c1', pattern: '/assistant' })
    const card = await screen.findByRole('group', { name: 'New product to confirm' })
    expect(screen.getByText(/Tap Confirm to add it/)).toBeInTheDocument()
    // The model's propose call is not shown as a lookup; the product search is.
    expect(screen.getByText(/Checked: product search · figures come from your records/)).toBeInTheDocument()
    expect(within(card).getByLabelText('Name')).toHaveValue('Sukari 1kg')
    expect(within(card).getByLabelText('Selling price (KSh)')).toHaveValue('160.00')

    const price = within(card).getByLabelText('Selling price (KSh)')
    await userEvent.clear(price)
    await userEvent.type(price, '165')
    await userEvent.type(within(card).getByLabelText('Stock now'), '12')
    await userEvent.click(within(card).getByRole('button', { name: 'Confirm' }))

    expect(await screen.findByText('Product added')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'View' })).toHaveAttribute('href', '/products/p9')
    expect(screen.queryByRole('button', { name: 'Confirm' })).not.toBeInTheDocument()
    expect(api.of('POST', '/api/v1/ai/conversations/c1/messages/m2/confirm')[0].body).toEqual({
      payload: { name: 'Sukari 1kg', selling_price: '165', cost_price: null, unit: 'piece', track_inventory: true, opening_stock: '12' },
    })
  })

  it('shows the backend error and keeps the card open when confirming fails', async () => {
    mockApi({
      ...base,
      'GET /api/v1/ai/conversations/c1': conversation([userMsg, productProposal]),
      'POST /api/v1/ai/conversations/c1/messages/m2/confirm': () => apiError(409, 'CONFLICT', 'A product named Sukari 1kg already exists'),
    })
    renderWithProviders(<AssistantPage />, { path: '/assistant?c=c1', pattern: '/assistant' })
    const card = await screen.findByRole('group', { name: 'New product to confirm' })
    await userEvent.click(within(card).getByRole('button', { name: 'Confirm' }))
    expect(await within(card).findByRole('alert')).toHaveTextContent('A product named Sukari 1kg already exists')
    expect(within(card).getByRole('button', { name: 'Confirm' })).toBeEnabled()
  })

  it('rejects with Not now and shows a sale proposal read-only with its lines and payments', async () => {
    const saleProposal = {
      ...productProposal,
      id: 'm4',
      content: '2 × Mkate, cash KSh 130. Tap Confirm to record it.',
      proposal: {
        kind: 'sale',
        payload: { lines: [{ product_id: 'p1', quantity: '2', unit_price: '65.00' }], payments: [{ method: 'CASH', amount: '130.00', reference: null }], customer_id: null, note: null },
        status: 'PENDING',
        entity_id: null,
        applied_at: null,
      },
    }
    const api = mockApi({
      ...base,
      'GET /api/v1/ai/conversations/c1': conversation([userMsg, saleProposal]),
      'POST /api/v1/ai/conversations/c1/messages/m4/reject': () => json({ message: { ...saleProposal, proposal: { ...saleProposal.proposal, status: 'REJECTED' } }, kind: 'sale', entity_id: null }),
    })
    renderWithProviders(<AssistantPage />, { path: '/assistant?c=c1', pattern: '/assistant' })
    const card = await screen.findByRole('group', { name: 'Sale to confirm' })
    expect(within(card).getByText('2 × KSh 65')).toBeInTheDocument()
    expect(within(card).getByText('Paid: Cash KSh 130')).toBeInTheDocument()
    await userEvent.click(within(card).getByRole('button', { name: 'Not now' }))
    expect(await screen.findByText('Not recorded')).toBeInTheDocument()
    expect(api.of('POST', '/api/v1/ai/conversations/c1/messages/m4/reject')).toHaveLength(1)
    expect(screen.queryByRole('button', { name: 'Confirm' })).not.toBeInTheDocument()
  })

  it('shows an already-applied proposal locked with a link and no buttons', async () => {
    mockApi({
      ...base,
      'GET /api/v1/ai/conversations/c1': conversation([userMsg, { ...productProposal, proposal: { ...productProposal.proposal, status: 'APPLIED', entity_id: 'p9', applied_at: '2026-09-17T08:01:00Z' } }]),
    })
    renderWithProviders(<AssistantPage />, { path: '/assistant?c=c1', pattern: '/assistant' })
    expect(await screen.findByText('Product added')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'View' })).toHaveAttribute('href', '/products/p9')
    expect(screen.queryByRole('button', { name: 'Confirm' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Not now' })).not.toBeInTheDocument()
  })
})
