import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { sale } from '@/test/fixtures'
import { json, mockApi, renderWithProviders, staffSession } from '@/test/render'

import SaleDetailPage from './SaleDetailPage'

describe('SaleDetailPage', () => {
  it('lets the owner void a sale with a reason', async () => {
    let current = sale()
    const api = mockApi({
      'GET /api/v1/sales/s-1': () => json(current),
      'POST /api/v1/sales/s-1/void': () => {
        current = sale({ status: 'VOIDED', voided_at: '2026-09-15T10:00:00Z', void_reason: 'Wrong item' })
        return json(current)
      },
    })
    renderWithProviders(<SaleDetailPage />, { path: '/sales/s-1', pattern: '/sales/:saleId' })
    expect(await screen.findByText('Completed')).toBeInTheDocument()
    expect(screen.getByText('Bread')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Void sale' }))
    const dialog = await screen.findByRole('dialog', { name: 'Void this sale?' })
    expect(within(dialog).getByRole('button', { name: 'Void sale' })).toBeDisabled()
    await userEvent.type(within(dialog).getByLabelText('Reason'), 'Wrong item')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Void sale' }))
    await waitFor(() => expect(api.of('POST', '/api/v1/sales/s-1/void')[0]?.body).toEqual({ reason: 'Wrong item' }))
    expect(await screen.findByText('This sale was voided')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Void sale' })).not.toBeInTheDocument()
  })

  it('does not offer void to staff', async () => {
    mockApi({ 'GET /api/v1/sales/s-1': sale() })
    renderWithProviders(<SaleDetailPage />, { session: staffSession, path: '/sales/s-1', pattern: '/sales/:saleId' })
    expect(await screen.findByText('Completed')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Void sale' })).not.toBeInTheDocument()
  })
})
