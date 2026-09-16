import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { product } from '@/test/fixtures'
import { apiError, json, mockApi, renderWithProviders, staffSession } from '@/test/render'

import InventoryPage from './InventoryPage'

const movement = { id: 'm-1', product_id: 'p-bread', movement_type: 'RESTOCK', quantity_delta: '10.000', quantity_after: '10.000', unit_cost: '40.00', total_cost: '400.00', sale_id: null, supplier_name: 'Bakery', reason: null, occurred_at: '2026-09-14T06:00:00Z', created_at: '2026-09-14T06:00:00Z', created_by: 'u-owner' }

describe('InventoryPage', () => {
  it('shows low stock and movements, and explains a 403 when staff may not restock', async () => {
    const api = mockApi({
      'GET /api/v1/inventory/low-stock': [{ product_id: 'p-bread', name: 'Bread', sku: null, unit: 'piece', stock_quantity: '2.000', threshold: '5.000' }],
      'GET /api/v1/inventory/movements': [movement],
      'GET /api/v1/products': [product()],
      'POST /api/v1/inventory/restock': () => apiError(403, 'FORBIDDEN', 'Owner only'),
    })
    renderWithProviders(<InventoryPage />, { session: staffSession, path: '/inventory', pattern: '/inventory' })
    expect(await screen.findByText('Bakery')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Adjust' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Opening stock' })).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Restock' }))
    const dialog = await screen.findByRole('dialog', { name: 'Restock' })
    await userEvent.click(await within(dialog).findByRole('button', { name: /Bread/ }))
    await userEvent.type(within(dialog).getByLabelText('Quantity (piece)'), '20')
    expect(within(dialog).getByLabelText('Cost per unit (KSh)')).toHaveValue('40.00')
    await userEvent.clear(within(dialog).getByLabelText('Cost per unit (KSh)'))
    await userEvent.type(within(dialog).getByLabelText('Cost per unit (KSh)'), '40')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Add stock' }))
    await waitFor(() => expect(api.of('POST', '/api/v1/inventory/restock')).toHaveLength(1))
    expect(api.of('POST', '/api/v1/inventory/restock')[0].body).toMatchObject({ product_id: 'p-bread', quantity: '20', unit_cost: '40' })
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Only the owner can do this')
  })

  it('lets the owner record an adjustment as a signed delta', async () => {
    const api = mockApi({
      'GET /api/v1/inventory/low-stock': [],
      'GET /api/v1/inventory/movements': [],
      'GET /api/v1/products': [product()],
      'POST /api/v1/inventory/adjust': () => json({ ...movement, movement_type: 'ADJUSTMENT', quantity_delta: '-2.000' }, 201),
    })
    renderWithProviders(<InventoryPage />, { path: '/inventory', pattern: '/inventory' })
    await userEvent.click(await screen.findByRole('button', { name: 'Adjust' }))
    const dialog = await screen.findByRole('dialog', { name: 'Adjust stock' })
    await userEvent.click(await within(dialog).findByRole('button', { name: /Bread/ }))
    await userEvent.type(within(dialog).getByLabelText('Quantity (piece)'), '2')
    await userEvent.type(within(dialog).getByLabelText('Reason'), 'Damaged by rain')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save adjustment' }))
    await waitFor(() => expect(api.of('POST', '/api/v1/inventory/adjust')).toHaveLength(1))
    expect(api.of('POST', '/api/v1/inventory/adjust')[0].body).toEqual({ product_id: 'p-bread', quantity_delta: '-2', reason: 'Damaged by rain' })
  })
})
