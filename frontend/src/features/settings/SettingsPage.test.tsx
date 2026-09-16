import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { sessionStore } from '@/lib/session'
import { json, mockApi, renderWithProviders, staffSession } from '@/test/render'

import SettingsPage from './SettingsPage'

const business = { id: 'b1', name: 'Amina Duka', business_type: 'GENERAL_SHOP', phone: null, address: null, currency: 'KES', timezone: 'Africa/Nairobi', settings: { staff_can_restock: false, sale_backdate_days: 0, low_stock_default_threshold: 5 }, is_active: true, created_at: '2026-09-01T06:00:00Z' }
const members = [
  { user_id: 'u-owner', full_name: 'Amina Wanjiru', phone: '+254712345678', email: null, role: 'OWNER', is_active: true, must_change_password: false, last_login_at: null, joined_at: '2026-09-01T06:00:00Z' },
  { user_id: 'u-staff', full_name: 'Brian Staff', phone: '+254700000002', email: null, role: 'STAFF', is_active: true, must_change_password: true, last_login_at: null, joined_at: '2026-09-02T06:00:00Z' },
]

describe('SettingsPage', () => {
  it('lets the owner edit the business and manage the team', async () => {
    const api = mockApi({
      'GET /api/v1/business': business,
      'PATCH /api/v1/business': (init: RequestInit) => json({ ...business, ...JSON.parse(init.body as string) }),
      'GET /api/v1/users': members,
      'POST /api/v1/users': (init: RequestInit) => json({ ...members[1], user_id: 'u-new', ...JSON.parse(init.body as string) }, 201),
      'PATCH /api/v1/users/u-staff': () => json({ ...members[1], is_active: false }),
    })
    renderWithProviders(<SettingsPage />, { path: '/settings', pattern: '/settings' })
    expect(await screen.findByText('No — owner only')).toBeInTheDocument()
    expect(await screen.findByText('Must change password')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Edit' }))
    const name = screen.getByLabelText('Business name')
    await userEvent.clear(name)
    await userEvent.type(name, 'Amina Supermarket')
    await userEvent.click(screen.getByLabelText(/Staff can record restocks/))
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }))
    await waitFor(() => expect(api.of('PATCH', '/api/v1/business')).toHaveLength(1))
    expect(api.of('PATCH', '/api/v1/business')[0].body).toMatchObject({ name: 'Amina Supermarket', settings: { staff_can_restock: true, sale_backdate_days: 0, low_stock_default_threshold: 5 } })
    expect(await screen.findByText('Yes')).toBeInTheDocument()
    expect(sessionStore.get()?.business.name).toBe('Amina Supermarket')

    await userEvent.click(screen.getByRole('button', { name: 'Add staff' }))
    const dialog = await screen.findByRole('dialog', { name: 'Add a staff member' })
    await userEvent.type(within(dialog).getByLabelText('Full name'), 'Cynthia Achieng')
    await userEvent.type(within(dialog).getByLabelText('Phone'), '0722000333')
    await userEvent.type(within(dialog).getByLabelText('Temporary password'), 'welcome-2026')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Add staff' }))
    await waitFor(() => expect(api.of('POST', '/api/v1/users')[0]?.body).toEqual({ full_name: 'Cynthia Achieng', phone: '0722000333', email: null, password: 'welcome-2026' }))

    await userEvent.click(screen.getByRole('button', { name: 'Actions for Brian Staff' }))
    await userEvent.click(await screen.findByRole('menuitem', { name: 'Deactivate' }))
    const confirm = await screen.findByRole('dialog', { name: 'Deactivate Brian Staff?' })
    await userEvent.click(within(confirm).getByRole('button', { name: 'Deactivate' }))
    await waitFor(() => expect(api.of('PATCH', '/api/v1/users/u-staff')[0]?.body).toEqual({ is_active: false }))
  })

  it('is read-only for staff and never calls owner endpoints', async () => {
    const api = mockApi({})
    renderWithProviders(<SettingsPage />, { session: staffSession, path: '/settings', pattern: '/settings' })
    expect(screen.getByText('Only the owner can change these.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument()
    expect(screen.queryByText('Team')).not.toBeInTheDocument()
    expect(api.calls).toHaveLength(0)
  })
})
