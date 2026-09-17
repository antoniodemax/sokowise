import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route } from 'react-router'
import { describe, expect, it } from 'vitest'

import { apiError, json, mockApi, renderWithProviders } from '@/test/render'

import ReceiptsPage from './ReceiptsPage'
import { checkReceiptFile } from './status'

const uploaded = { id: 'r1', status: 'UPLOADED', original_filename: 'receipt.jpg', mime_type: 'image/jpeg', size_bytes: 3, supplier_name: null, receipt_number: null, receipt_date: null, currency: null, extracted_subtotal: null, extracted_total: null, extraction_provider: null, extraction_model: null, extraction_error: null, warnings: [], line_count: 0, extracted_at: null, confirmed_at: null, created_at: '2026-09-17T08:00:00Z', updated_at: '2026-09-17T08:00:00Z', lines: [] }

describe('ReceiptsPage', () => {
  it('rejects the wrong kind of file before uploading', async () => {
    const api = mockApi({ 'GET /api/v1/receipts': [] })
    renderWithProviders(<ReceiptsPage />, { path: '/inventory/receipts', pattern: '/inventory/receipts' })
    expect(await screen.findByText('No receipts yet')).toBeInTheDocument()
    await userEvent.upload(screen.getByLabelText('Receipt photo'), new File(['<svg/>'], 'receipt.svg', { type: 'image/svg+xml' }), { applyAccept: false })
    expect(await screen.findByRole('alert')).toHaveTextContent('Choose a JPEG, PNG or WebP photo')
    expect(api.of('POST', '/api/v1/receipts')).toHaveLength(0)
    expect(checkReceiptFile(new File([new Uint8Array(9 * 1024 * 1024)], 'big.jpg', { type: 'image/jpeg' }))).toMatch(/too large/)
    expect(checkReceiptFile(new File(['x'], 'ok.png', { type: 'image/png' }))).toBeNull()
  })

  it('uploads a photo, reads it, and opens the review page', async () => {
    const api = mockApi({
      'GET /api/v1/receipts': [],
      'POST /api/v1/receipts': () => json(uploaded, 201),
      'POST /api/v1/receipts/r1/process': () => json({ ...uploaded, status: 'READY_FOR_REVIEW' }),
    })
    renderWithProviders(<ReceiptsPage />, { path: '/inventory/receipts', pattern: '/inventory/receipts', extraRoutes: <Route path="/inventory/receipts/:id" element={<h1>Review page</h1>} /> })
    await screen.findByText('No receipts yet')
    await userEvent.upload(screen.getByLabelText('Receipt photo'), new File(['jpg'], 'receipt.jpg', { type: 'image/jpeg' }))
    await waitFor(() => expect(api.of('POST', '/api/v1/receipts')).toHaveLength(1))
    expect(api.of('POST', '/api/v1/receipts')[0].headers.Authorization).toBe('Bearer token')
    expect(await screen.findByRole('heading', { name: 'Review page' })).toBeInTheDocument()
    expect(api.of('POST', '/api/v1/receipts/r1/process')).toHaveLength(1)
  })

  it('shows the backend reason when the upload is refused', async () => {
    mockApi({ 'GET /api/v1/receipts': [], 'POST /api/v1/receipts': () => apiError(422, 'RECEIPT_IMAGE_INVALID', 'The file is not a readable image') })
    renderWithProviders(<ReceiptsPage />, { path: '/inventory/receipts', pattern: '/inventory/receipts' })
    await screen.findByText('No receipts yet')
    await userEvent.upload(screen.getByLabelText('Receipt photo'), new File(['x'], 'receipt.jpg', { type: 'image/jpeg' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('The file is not a readable image')
  })

  it('lists receipts with their status', async () => {
    mockApi({ 'GET /api/v1/receipts': [{ ...uploaded, status: 'CONFIRMED', supplier_name: 'Kamau Wholesalers', extracted_total: '2205.00', line_count: 3 }] })
    renderWithProviders(<ReceiptsPage />, { path: '/inventory/receipts', pattern: '/inventory/receipts' })
    expect(await screen.findByRole('button', { name: 'Kamau Wholesalers' })).toBeInTheDocument()
    expect(screen.getByText('Stock added')).toBeInTheDocument()
    expect(screen.getByText('KSh 2,205')).toBeInTheDocument()
  })
})
