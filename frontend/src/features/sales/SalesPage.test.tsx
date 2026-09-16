import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { sale } from '@/test/fixtures'
import { mockApi, renderWithProviders, staffSession } from '@/test/render'

import SalesPage from './SalesPage'

describe('SalesPage', () => {
  it('asks for today as business-timezone instants for the owner', async () => {
    const api = mockApi({ 'GET /api/v1/sales': [sale()] })
    renderWithProviders(<SalesPage />, { path: '/sales', pattern: '/sales' })
    expect(await screen.findByText(/2× Bread/)).toBeInTheDocument()
    const params = api.of('GET', '/api/v1/sales')[0].url.searchParams
    expect(params.get('date_from')).toMatch(/T21:00:00\.000Z$/) // midnight in Nairobi
    expect(params.get('date_to')).toMatch(/T21:00:00\.000Z$/)
    expect(new Date(params.get('date_to')!).getTime() - new Date(params.get('date_from')!).getTime()).toBe(86_400_000)
  })

  it('shows staff their own day without date filters', async () => {
    const api = mockApi({ 'GET /api/v1/sales': [] })
    renderWithProviders(<SalesPage />, { session: staffSession, path: '/sales', pattern: '/sales' })
    expect(await screen.findByText('No sales here')).toBeInTheDocument()
    expect(screen.queryByLabelText('From')).not.toBeInTheDocument()
    expect(api.of('GET', '/api/v1/sales')[0].url.searchParams.has('date_from')).toBe(false)
  })
})
