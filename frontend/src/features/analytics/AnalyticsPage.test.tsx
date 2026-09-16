import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { mockApi, renderWithProviders } from '@/test/render'

import AnalyticsPage from './AnalyticsPage'

const summary = {
  period: { timezone: 'Africa/Nairobi', date_from: '2026-09-01', date_to: '2026-09-16' },
  sales_count: 12, revenue: '12000.00', discounts: '100.00', cogs: '7000.00', lines_missing_cost: 3, products_missing_cost: 2,
  gross_profit: '5000.00', expenses: '1500.00', net_profit: '3500.00',
  tender_split: { CASH: '8000.00', MPESA: '3000.00', CREDIT: '1000.00' }, cash_collected: { CASH: '8200.00', MPESA: '3000.00' }, cash_collected_total: '11200.00', receivables_outstanding: '900.00',
}

describe('AnalyticsPage', () => {
  it('shows real figures with accurate terminology, missing-cost warnings and an accessible chart', async () => {
    const api = mockApi({
      'GET /api/v1/analytics/summary': summary,
      'GET /api/v1/analytics/timeseries': { period: summary.period, granularity: 'day', buckets: [{ bucket_start: '2026-09-15T00:00:00+03:00', sales_count: 3, revenue: '3000.00', discounts: '0.00', cogs: '2000.00', lines_missing_cost: 0, gross_profit: '1000.00', cash_collected: '3000.00', expenses: '200.00', net_profit: '800.00' }] },
      'GET /api/v1/analytics/products': [{ product_id: 'p-bread', name: 'Bread', is_active: true, category_id: null, quantity: '40.000', revenue: '2200.00', cogs: '1600.00', gross_profit: '600.00', sales_count: 10, lines_missing_cost: 1 }],
      'GET /api/v1/analytics/categories': [{ category_id: null, name: null, quantity: '40.000', revenue: '2200.00', cogs: '1600.00', gross_profit: '600.00', lines_missing_cost: 0 }],
      'GET /api/v1/analytics/expenses': { period: summary.period, total: '1500.00', count: 2, by_category: [{ key: 'RENT', total: '1500.00', count: 2 }], by_method: { CASH: '1500.00', MPESA: '0.00' } },
      'GET /api/v1/analytics/slow-products': [{ product_id: 'p-x', name: 'Umbrella', stock_quantity: '4.000', last_sold_at: null }],
    })
    renderWithProviders(<AnalyticsPage />, { path: '/analytics', pattern: '/analytics' })
    expect(await screen.findByText('Profit is understated')).toBeInTheDocument()
    expect(screen.getByText(/2 products have no cost price, so 3 sale lines count as pure profit/)).toBeInTheDocument()
    expect(screen.getByText('Owed to you, not cash received')).toBeInTheDocument()
    expect(screen.getByText('KSh 11,200')).toBeInTheDocument()
    expect(api.of('GET', '/api/v1/analytics/summary')[0].url.searchParams.get('period')).toBe('this_month')

    const table = await screen.findByRole('table', { name: 'Revenue, gross profit and expenses by day' })
    expect(within(table).getByRole('rowheader', { name: '15 Sept' })).toBeInTheDocument()
    expect(within(table).getByText('KSh 1,000')).toBeInTheDocument()
    expect(await screen.findByText('cost missing on 1 line')).toBeInTheDocument()
    expect(await screen.findByText('Uncategorised')).toBeInTheDocument()
    expect(await screen.findByText('Umbrella')).toBeInTheDocument()
    expect(screen.getByText('Never')).toBeInTheDocument()
  })
})
