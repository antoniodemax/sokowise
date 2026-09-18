import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'

import { AuthContext, type AuthContextValue } from '@/features/auth/auth-context'
import { ownerSession } from '@/test/render'

import HomePage from './HomePage'

function renderHome(session: AuthContextValue['session'] = null) {
  const fetchMock = vi.fn()
  vi.stubGlobal('fetch', fetchMock)
  const auth: AuthContextValue = { session, restoring: false, login: vi.fn(), register: vi.fn(), changePassword: vi.fn(), signInWithGoogle: vi.fn(), registerWithGoogle: vi.fn(), logout: vi.fn(), logoutAll: vi.fn() }
  render(
    <AuthContext.Provider value={auth}>
      <MemoryRouter initialEntries={['/']}>
        <HomePage />
      </MemoryRouter>
    </AuthContext.Provider>,
  )
  return fetchMock
}

describe('HomePage', () => {
  it('renders every section for an anonymous visitor without calling the API', () => {
    const fetchMock = renderHome()
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Know your business')
    for (const name of ['Everything you need to keep your business on track.', 'Built around how small businesses here actually run.', 'Made for the businesses on every Kenyan street.', 'Up and running in an afternoon.', 'This is the actual SokoWise.', 'Simple, honest and built for the counter.', 'Ready to understand your business better?']) {
      expect(screen.getByRole('heading', { level: 2, name })).toBeInTheDocument()
    }
    expect(screen.getByRole('main')).toBeInTheDocument()
    expect(screen.getByRole('contentinfo')).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
    expect(document.title).toBe('SokoWise — Simple business management for Kenyan small businesses')
  })

  it('does not claim the AI copilot exists yet', () => {
    renderHome()
    const card = screen.getByRole('heading', { level: 3, name: 'AI copilot' }).closest('li')!
    expect(within(card).getByText('Coming soon')).toBeInTheDocument()
    expect(within(card).getByText(/not available yet/)).toBeInTheDocument()
  })

  it('links every call to action to register or login', () => {
    renderHome()
    const starts = screen.getAllByRole('link', { name: /Get started/ })
    const signIns = screen.getAllByRole('link', { name: 'Sign in' })
    expect(starts.length).toBeGreaterThanOrEqual(3)
    expect(signIns.length).toBeGreaterThanOrEqual(3)
    for (const link of starts) expect(link).toHaveAttribute('href', '/register')
    for (const link of signIns) expect(link).toHaveAttribute('href', '/login')
    expect(screen.queryByRole('link', { name: /dashboard/i })).not.toBeInTheDocument()
  })

  it('opens and closes the mobile menu with the section and auth links inside', async () => {
    renderHome()
    const button = screen.getByRole('button', { name: 'Open menu' })
    expect(button).toHaveAttribute('aria-expanded', 'false')
    await userEvent.click(button)
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByRole('link', { name: 'Features' })).toHaveAttribute('href', '#features')
    expect(within(dialog).getByRole('link', { name: 'Get started' })).toHaveAttribute('href', '/register')
    await userEvent.click(within(dialog).getByRole('link', { name: 'How it works' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('offers the dashboard instead of sign in when a session exists', () => {
    renderHome(ownerSession)
    expect(screen.getAllByRole('link', { name: 'Go to dashboard' })[0]).toHaveAttribute('href', '/dashboard')
    expect(screen.queryByRole('navigation', { name: 'Site' })?.querySelector('a[href="/login"]')).toBeNull()
  })

  it('labels product images as example data and describes the photographs', () => {
    renderHome()
    const productShots = screen.getAllByRole('img', { name: /Karibu Mini Mart, an example business/i })
    expect(productShots.map((img) => img.getAttribute('src'))).toEqual(['/marketing/dashboard-phone.webp', '/marketing/dashboard.webp'])
    expect(screen.getByText('Example data')).toBeInTheDocument()
    expect(screen.getByText('The owner\'s dashboard, shown with example data.')).toBeInTheDocument()
    for (const name of [/food-stall owner/i, /street-food cook/i, /fruit vendor/i]) {
      const photo = screen.getByRole('img', { name })
      expect(photo).toHaveAttribute('srcset')
      expect(photo.getAttribute('src')).toMatch(/^\/marketing\/.+\.webp$/)
    }
  })

  it('the header and footer logos scroll back to the top of the homepage', async () => {
    renderHome()
    const scrollTo = vi.fn()
    vi.stubGlobal('scrollTo', scrollTo)
    const logos = [screen.getByRole('link', { name: 'SokoWise home' }), screen.getByRole('link', { name: 'Back to the top of the homepage' })]
    for (const logo of logos) {
      expect(logo).toHaveAttribute('href', '/')
      await userEvent.click(logo)
    }
    expect(scrollTo).toHaveBeenCalledTimes(2)
    expect(scrollTo).toHaveBeenLastCalledWith({ top: 0, behavior: 'smooth' })
    vi.unstubAllGlobals()
  })
})
