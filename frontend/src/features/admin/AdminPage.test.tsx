import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { Route } from 'react-router'

import { RequirePlatformAdmin } from '@/app/guards'
import { AppShell } from '@/app/layouts/AppShell'
import { apiError, json, mockApi, ownerSession, renderWithProviders } from '@/test/render'

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
    expect(within(totals).getByText(/33% of businesses recorded a sale in 7 days/)).toBeInTheDocument()
    const recording = screen.getByText('Sales recorded').closest('dl') as HTMLElement
    expect(within(recording).getByText('KSh 4,250')).toBeInTheDocument()
    expect(within(recording).getByText('KSh 540')).toBeInTheDocument()
    expect(within(recording).getByText('9')).toBeInTheDocument()
    expect(screen.getByText(/2/, { selector: 'span.tabular' })).toBeInTheDocument() // sign-ups in 30 days
    expect(screen.getByRole('list', { name: 'Sign-ups per day' }).children).toHaveLength(30)
    const table = screen.getByRole('table')
    expect(within(table).getByText('Nairobi Test Shop A')).toBeInTheDocument()
    expect(within(table).getByText('Salon / barber')).toBeInTheDocument()
    expect(within(table).getByText('inactive')).toBeInTheDocument()
    expect(within(table).getAllByText('today').length).toBeGreaterThan(0)
    // phones get one card per business with the same facts
    const cards = screen.getByRole('list', { name: 'Businesses' })
    expect(within(cards).getByText('Salon B')).toBeInTheDocument()
    expect(within(cards).getByText('never')).toBeInTheDocument()
    expect(within(table).getByText('not since sign-up')).toBeInTheDocument()
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

  it('deletes a business only after the admin types its name, then refreshes the overview', async () => {
    const api = mockApi({
      'GET /api/v1/admin/overview': overview,
      'DELETE /api/v1/admin/businesses/b2': () => json({ business_id: 'b2', name: 'Salon B', users_deleted: 1, receipt_images_deleted: 0 }),
    })
    renderWithProviders(<AdminPage />, { session: adminSession, path: '/admin', pattern: '/admin' })
    await screen.findAllByText('Businesses')
    await userEvent.click(screen.getAllByRole('button', { name: 'Delete Salon B' })[0])
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByRole('heading', { name: 'Delete Salon B?' })).toBeInTheDocument()
    const confirm = within(dialog).getByRole('button', { name: 'Delete business' })
    expect(confirm).toBeDisabled()
    await userEvent.type(within(dialog).getByLabelText('Type Salon B to confirm'), 'Salon')
    expect(confirm).toBeDisabled()
    await userEvent.type(within(dialog).getByLabelText('Type Salon B to confirm'), ' B')
    expect(confirm).toBeEnabled()
    await userEvent.click(confirm)
    await waitFor(() => expect(api.of('DELETE', '/api/v1/admin/businesses/b2')).toHaveLength(1))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(api.of('GET', '/api/v1/admin/overview').length).toBeGreaterThan(1)
  })

  it('shows the refusal when the admin tries to delete their own business', async () => {
    mockApi({
      'GET /api/v1/admin/overview': overview,
      'DELETE /api/v1/admin/businesses/b1': () => apiError(409, 'OWN_BUSINESS', 'You belong to this business. Delete it from another admin account.'),
    })
    renderWithProviders(<AdminPage />, { session: adminSession, path: '/admin', pattern: '/admin' })
    await screen.findAllByText('Businesses')
    await userEvent.click(screen.getAllByRole('button', { name: 'Delete Nairobi Test Shop A' })[0])
    const dialog = await screen.findByRole('dialog')
    await userEvent.type(within(dialog).getByLabelText('Type Nairobi Test Shop A to confirm'), 'Nairobi Test Shop A')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Delete business' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('You belong to this business')
  })
})
