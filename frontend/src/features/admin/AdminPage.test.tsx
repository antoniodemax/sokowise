import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { Route } from 'react-router'

import { RequirePlatformAdmin } from '@/app/guards'
import { AppShell } from '@/app/layouts/AppShell'
import { mockApi, ownerSession, renderWithProviders } from '@/test/render'

import AdminPage from './AdminPage'

const overview = {
  generated_at: '2026-09-18T12:00:00Z',
  timezone: 'Africa/Nairobi',
  totals: { businesses: 3, businesses_active: 3, users: 4, owners: 3, staff: 1, products: 12, customers: 5, sales: 9, revenue: '4250.00', expenses: 2, credit_outstanding: '540.00', mpesa_messages: 2, receipts: 1, copilot_messages: 0, proposals_applied: 0 },
  last_7_days: { days: 7, new_businesses: 2, sales: 9, revenue: '4250.00', businesses_with_sales: 1, users_signed_in: 3 },
  last_30_days: { days: 30, new_businesses: 3, sales: 9, revenue: '4250.00', businesses_with_sales: 1, users_signed_in: 4 },
  signups_by_day: Array.from({ length: 30 }, (_, i) => ({ day: `2026-08-${String(20 + i).padStart(2, '0')}`, businesses: i === 29 ? 2 : 0 })).map((d, i) => (i === 29 ? { ...d, day: '2026-09-18' } : d)),
  businesses: [
    { id: 'b1', name: 'Nairobi Test Shop A', business_type: 'GENERAL_SHOP', is_active: true, created_at: '2026-09-18T08:00:00Z', products: 4, sales: 9, last_sale_at: '2026-09-18T11:30:00Z', last_login_at: '2026-09-18T11:00:00Z' },
    { id: 'b2', name: 'Salon B', business_type: 'SALON', is_active: false, created_at: '2026-09-17T08:00:00Z', products: 8, sales: 0, last_sale_at: null, last_login_at: null },
  ],
}
const adminSession = { ...ownerSession, is_platform_admin: true }

describe('AdminPage', () => {
  it('shows platform totals, sign-ups and the business table from the overview', async () => {
    mockApi({ 'GET /api/v1/admin/overview': overview })
    renderWithProviders(<AdminPage />, { session: adminSession, path: '/admin', pattern: '/admin' })
    expect(await screen.findByRole('heading', { name: 'Admin' })).toBeInTheDocument()
    const totals = (await screen.findAllByText('Businesses'))[0].closest('section') as HTMLElement
    expect(within(totals).getByText('3', { selector: 'p' })).toBeInTheDocument()
    expect(within(totals).getByText(/3 owners · 1 staff · 3 signed in this week/)).toBeInTheDocument()
    expect(within(totals).getByText('KSh 4,250')).toBeInTheDocument()
    expect(within(totals).getByText(/deni outstanding KSh 540/)).toBeInTheDocument()
    expect(screen.getByRole('list', { name: 'Sign-ups per day' }).children).toHaveLength(30)
    const table = screen.getByRole('table')
    expect(within(table).getByText('Nairobi Test Shop A')).toBeInTheDocument()
    expect(within(table).getByText('Salon / barber')).toBeInTheDocument()
    expect(within(table).getByText('inactive')).toBeInTheDocument()
    // Nothing on the page is a phone number or a customer name.
    expect(screen.queryByText(/\+254/)).not.toBeInTheDocument()
  })

  it('shows the not-found page and no Admin link for a session without the platform flag', async () => {
    const api = mockApi({ 'GET /api/v1/admin/overview': overview })
    renderWithProviders(<p>unused</p>, {
      session: ownerSession,
      path: '/admin',
      pattern: '/unused',
      extraRoutes: (
        <Route element={<AppShell />}>
          <Route element={<RequirePlatformAdmin />}>
            <Route path="/admin" element={<AdminPage />} />
          </Route>
        </Route>
      ),
    })
    expect(await screen.findByText('Page not found')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Admin' })).not.toBeInTheDocument()
    expect(api.of('GET', '/api/v1/admin/overview')).toHaveLength(0)
  })

  it('shows the Admin link in the navigation for a platform admin', async () => {
    mockApi({ 'GET /api/v1/admin/overview': overview })
    renderWithProviders(<p>unused</p>, {
      session: adminSession,
      path: '/admin',
      pattern: '/unused',
      extraRoutes: (
        <Route element={<AppShell />}>
          <Route element={<RequirePlatformAdmin />}>
            <Route path="/admin" element={<AdminPage />} />
          </Route>
        </Route>
      ),
    })
    expect(await screen.findByRole('heading', { name: 'Admin' })).toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: 'Admin' }).length).toBeGreaterThan(0)
  })
})
