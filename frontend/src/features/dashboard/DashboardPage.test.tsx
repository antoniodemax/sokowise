import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { mockApi, renderWithProviders, staffSession } from '@/test/render'

import DashboardPage from './DashboardPage'

const lowStock = [{ product_id: 'p-bread', name: 'Bread', sku: null, unit: 'piece', stock_quantity: '2.000', threshold: '5.000' }]

describe('DashboardPage', () => {
  it('shows staff quick actions and low stock without touching owner-only figures', async () => {
    const api = mockApi({ 'GET /api/v1/inventory/low-stock': lowStock })
    renderWithProviders(<DashboardPage />, { session: staffSession })
    expect(await screen.findByText('2 piece left')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'New sale' })).toHaveAttribute('href', '/sales/new')
    expect(api.of('GET', '/api/v1/analytics/summary')).toHaveLength(0)
    expect(api.of('GET', '/api/v1/debtors')).toHaveLength(0)
  })

  it('shows the owner figures, low stock and top debtors', async () => {
    mockApi({
      'GET /api/v1/inventory/low-stock': lowStock,
      'GET /api/v1/debtors': [{ customer_id: 'c-amina', name: 'Amina Njeri', phone: null, balance: '900.00', credit_limit: null, oldest_unpaid_charge_at: null }],
      'GET /api/v1/analytics/summary': { period: { timezone: 'Africa/Nairobi', date_from: '2026-09-16', date_to: '2026-09-16' }, sales_count: 2, revenue: '1000.00', discounts: '0.00', cogs: '600.00', lines_missing_cost: 0, products_missing_cost: 0, gross_profit: '400.00', expenses: '0.00', net_profit: '400.00', tender_split: { CASH: '1000.00', MPESA: '0.00', CREDIT: '0.00' }, cash_collected: { CASH: '1000.00', MPESA: '0.00' }, cash_collected_total: '1000.00', receivables_outstanding: '900.00' },
    })
    renderWithProviders(<DashboardPage />)
    expect(await screen.findAllByText('KSh 1,000')).not.toHaveLength(0)
    expect(await screen.findByText('Amina Njeri')).toBeInTheDocument()
    expect(screen.getByText('2 piece left')).toBeInTheDocument()
  })
})
