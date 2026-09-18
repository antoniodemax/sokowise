import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route } from 'react-router'
import { describe, expect, it } from 'vitest'

import { product } from '@/test/fixtures'
import { json, mockApi, renderWithProviders } from '@/test/render'

import type { StarterItem } from './api'
import SetupPage from './SetupPage'

const starter: StarterItem[] = [
  { name: 'Sukari 1kg', selling_price: '160.00', cost_price: '135.00', unit: 'piece', track_inventory: true },
  { name: 'Mkate 400g', selling_price: '60.00', cost_price: '50.00', unit: 'piece', track_inventory: true },
  { name: 'Other', selling_price: '0.00', cost_price: null, unit: 'other', track_inventory: false },
]

describe('SetupPage', () => {
  it('ticks items, edits a price, and adds them in one request', async () => {
    const api = mockApi({
      'GET /api/v1/products/starter': starter,
      'POST /api/v1/products/bulk': () => json([product({ name: 'Sukari 1kg' }), product({ id: 'p-other', name: 'Other' })], 201),
    })
    renderWithProviders(<SetupPage />, { path: '/setup', pattern: '/setup', extraRoutes: <Route path="/dashboard" element={<h1>Dashboard</h1>} /> })
    expect(await screen.findByText('Sukari 1kg')).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: 'Sell Other' })).toBeChecked() // always on for quick sales
    expect(screen.getByRole('button', { name: /Add 1 item/ })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('checkbox', { name: 'Sell Sukari 1kg' }))
    const price = screen.getByLabelText('Price of Sukari 1kg')
    await userEvent.clear(price)
    await userEvent.type(price, '165')
    await userEvent.type(screen.getByLabelText('Stock of Sukari 1kg'), '20')
    expect(screen.queryByLabelText('Stock of Other')).not.toBeInTheDocument() // untracked: no stock box
    expect(screen.getByText('2 ticked')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Add 2 items/ }))
    await waitFor(() => expect(api.of('POST', '/api/v1/products/bulk')).toHaveLength(1))
    expect(api.of('POST', '/api/v1/products/bulk')[0].body).toEqual({
      items: [
        { name: 'Sukari 1kg', selling_price: '165', cost_price: '135.00', unit: 'piece', track_inventory: true, opening_stock: '20' },
        { name: 'Other', selling_price: '0.00', cost_price: null, unit: 'other', track_inventory: false },
      ],
    })
    expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument()
  })

  it('blocks adding while a ticked price is not a valid amount', async () => {
    mockApi({ 'GET /api/v1/products/starter': starter })
    renderWithProviders(<SetupPage />, { path: '/setup', pattern: '/setup' })
    await userEvent.click(await screen.findByRole('checkbox', { name: 'Sell Mkate 400g' }))
    const price = screen.getByLabelText('Price of Mkate 400g')
    await userEvent.clear(price)
    await userEvent.type(price, 'abc')
    expect(screen.getByRole('alert')).toHaveTextContent('Check the price or stock of Mkate 400g')
    expect(screen.getByRole('button', { name: /Add 2 items/ })).toBeDisabled()
  })
})
