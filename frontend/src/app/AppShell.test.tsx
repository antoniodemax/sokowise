import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route } from 'react-router'
import { describe, expect, it } from 'vitest'

import { mockApi, renderWithProviders } from '@/test/render'

import { AppShell } from './layouts/AppShell'

function renderShell(path: string) {
  mockApi({})
  // The shell is a layout route: its pages render into its <Outlet />.
  return renderWithProviders(<p>unused</p>, {
    path,
    pattern: '/unused',
    extraRoutes: (
      <Route element={<AppShell />}>
        <Route path="/dashboard" element={<h1>Dashboard page</h1>} />
        <Route path="/analytics" element={<h1>Analytics page</h1>} />
      </Route>
    ),
  })
}

describe('AppShell', () => {
  it('links the logo and business name to the dashboard in the sidebar and the mobile header', async () => {
    renderShell('/analytics')
    const home = screen.getAllByRole('link', { name: 'Go to the dashboard' })
    expect(home).toHaveLength(2) // desktop sidebar + mobile header (CSS decides which shows)
    for (const link of home) expect(link).toHaveAttribute('href', '/dashboard')
    expect(home[0]).toHaveTextContent('Amina Duka')
    await userEvent.click(home[0])
    expect(await screen.findByRole('heading', { name: 'Dashboard page' })).toBeInTheDocument()
  })

  it('also offers the logo link inside the mobile drawer and closes the drawer on use', async () => {
    renderShell('/analytics')
    await userEvent.click(screen.getByRole('button', { name: 'Open menu' }))
    const drawer = await screen.findByRole('dialog')
    await userEvent.click(within(drawer).getByRole('link', { name: 'Go to the dashboard' }))
    expect(await screen.findByRole('heading', { name: 'Dashboard page' })).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})
