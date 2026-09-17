import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { product } from '@/test/fixtures'
import { apiError, json, mockApi, renderWithProviders } from '@/test/render'

import type { Receipt, ReceiptLine } from './api'
import ReceiptReviewPage from './ReceiptReviewPage'

const sugar = product({ id: 'p-sugar', name: 'Sukari 1kg', cost_price: '135.00' })
const oil1 = product({ id: 'p-oil1', name: 'Mafuta ya kupikia 1L', cost_price: '285.00' })
const oil2 = product({ id: 'p-oil2', name: 'Mafuta ya kupikia 2L', cost_price: '540.00' })

function line(overrides: Partial<ReceiptLine>): ReceiptLine {
  return {
    id: 'l1',
    position: 0,
    extracted_name: 'Sukari 1kg',
    extracted_sku: null,
    extracted_quantity: '10.000',
    extracted_unit_cost: '135.00',
    extracted_line_total: '1350.00',
    confidence: '0.95',
    warnings: [],
    match_status: 'MATCHED',
    matched_product_id: 'p-sugar',
    candidate_product_ids: [],
    review_status: 'PENDING',
    final_product_id: null,
    final_quantity: null,
    final_unit_cost: null,
    movement_id: null,
    ...overrides,
  }
}

function receipt(overrides: Partial<Receipt> = {}): Receipt {
  return {
    id: 'r1',
    status: 'READY_FOR_REVIEW',
    original_filename: 'IMG_1.jpg',
    mime_type: 'image/jpeg',
    size_bytes: 1000,
    supplier_name: 'Kamau Wholesalers',
    receipt_number: 'KW-1042',
    receipt_date: '2026-09-17',
    currency: 'KES',
    extracted_subtotal: '2205.00',
    extracted_total: '2205.00',
    extraction_provider: 'fake',
    extraction_model: null,
    extraction_error: null,
    warnings: [],
    line_count: 3,
    extracted_at: '2026-09-17T09:00:00Z',
    confirmed_at: null,
    created_at: '2026-09-17T08:59:00Z',
    updated_at: '2026-09-17T09:00:00Z',
    lines: [
      line({}),
      line({ id: 'l2', position: 1, extracted_name: 'Mafuta ya kupikia', extracted_quantity: '3.000', extracted_unit_cost: '285.00', extracted_line_total: '855.00', match_status: 'AMBIGUOUS', matched_product_id: null, candidate_product_ids: ['p-oil1', 'p-oil2'] }),
      line({ id: 'l3', position: 2, extracted_name: 'Mystery item', extracted_quantity: '1.000', extracted_unit_cost: '50.00', extracted_line_total: '60.00', confidence: '0.4', warnings: ['line_total_mismatch', 'low_confidence'], match_status: 'UNMATCHED', matched_product_id: null }),
    ],
    ...overrides,
  }
}

const base = { 'GET /api/v1/products': [sugar, oil1, oil2] }

describe('ReceiptReviewPage', () => {
  it('shows every line with its match status, uncertainty and warnings, and only pre-selects matched lines', async () => {
    mockApi({ ...base, 'GET /api/v1/receipts/r1': receipt() })
    renderWithProviders(<ReceiptReviewPage />, { path: '/inventory/receipts/r1', pattern: '/inventory/receipts/:receiptId' })
    expect(await screen.findByRole('heading', { level: 1 })).toHaveTextContent('Kamau Wholesalers')
    expect(screen.getByText('Needs your review')).toBeInTheDocument()
    expect(screen.getByText('Matched')).toBeInTheDocument()
    expect(screen.getByText('Which product?')).toBeInTheDocument()
    expect(screen.getByText('Not in your products')).toBeInTheDocument()
    expect(screen.getByText('Hard to read')).toBeInTheDocument()
    expect(screen.getByText('Quantity × cost does not equal the printed line total')).toBeInTheDocument()
    expect(screen.getByLabelText('Include Sukari 1kg')).toBeChecked()
    expect(screen.getByLabelText('Include Mafuta ya kupikia')).not.toBeChecked()
    expect(screen.getByLabelText('Include Mystery item')).not.toBeChecked()
    expect(screen.getByText('Products to restock').nextElementSibling).toHaveTextContent('1 of 3 lines')
    expect(screen.getByText('Total supplier cost').nextElementSibling).toHaveTextContent('KSh 1,350')
  })

  it('lets the owner pick a product for an ambiguous line, edit values, and confirms with the final decisions', async () => {
    const api = mockApi({
      ...base,
      'GET /api/v1/receipts/r1': receipt(),
      'POST /api/v1/receipts/r1/confirm': (init: RequestInit) => {
        const body = JSON.parse(init.body as string) as { lines: { line_id: string; product_id: string }[] }
        const confirmed = receipt({ status: 'CONFIRMED', confirmed_at: '2026-09-17T09:05:00Z', lines: receipt().lines.map((l) => ({ ...l, review_status: body.lines.some((c) => c.line_id === l.id) ? 'APPLIED' : 'SKIPPED' })) })
        return json({ receipt: confirmed, movements_created: body.lines.length })
      },
    })
    renderWithProviders(<ReceiptReviewPage />, { path: '/inventory/receipts/r1', pattern: '/inventory/receipts/:receiptId' })
    await screen.findByText('Which product?')
    // Resolve the ambiguous line through the product picker.
    await userEvent.click(screen.getAllByRole('button', { name: 'Choose a product' })[0])
    const picker = await screen.findByRole('dialog', { name: 'Which product is this?' })
    await userEvent.click(await within(picker).findByRole('button', { name: /Mafuta ya kupikia 1L/ }))
    expect(screen.getByLabelText('Include Mafuta ya kupikia')).toBeChecked()
    // Correct the sugar quantity and tick the cost update.
    const qty = screen.getByLabelText('Quantity', { selector: '#qty-l1' })
    await userEvent.clear(qty)
    await userEvent.type(qty, '8')
    await userEvent.click(screen.getAllByLabelText("Also make this the product's cost price")[1])
    expect(screen.getByText('Products to restock').nextElementSibling).toHaveTextContent('2 of 3 lines')
    expect(screen.getByText('Total supplier cost').nextElementSibling).toHaveTextContent('KSh 1,935') // 8×135 + 3×285

    await userEvent.click(screen.getByRole('button', { name: 'Add to stock' }))
    const dialog = await screen.findByRole('dialog', { name: 'Add 2 products to stock?' })
    await userEvent.click(within(dialog).getByRole('button', { name: 'Add to stock' }))
    await waitFor(() => expect(api.of('POST', '/api/v1/receipts/r1/confirm')).toHaveLength(1))
    expect(api.of('POST', '/api/v1/receipts/r1/confirm')[0].body).toEqual({
      lines: [
        { line_id: 'l1', product_id: 'p-sugar', quantity: '8', unit_cost: '135.00', update_cost_price: false },
        { line_id: 'l2', product_id: 'p-oil1', quantity: '3', unit_cost: '285.00', update_cost_price: true },
      ],
      supplier_name: 'Kamau Wholesalers',
    })
    expect(await screen.findByText('Stock has been added')).toBeInTheDocument()
    expect(screen.getAllByText('Restocked')).toHaveLength(2)
    expect(screen.getByText('Skipped')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Add to stock' })).not.toBeInTheDocument()
  })

  it('surfaces a confirmation failure and keeps the review editable', async () => {
    mockApi({
      ...base,
      'GET /api/v1/receipts/r1': receipt({ lines: [line({})] }),
      'POST /api/v1/receipts/r1/confirm': () => apiError(409, 'PRODUCT_ARCHIVED', 'This product is archived'),
    })
    renderWithProviders(<ReceiptReviewPage />, { path: '/inventory/receipts/r1', pattern: '/inventory/receipts/:receiptId' })
    await userEvent.click(await screen.findByRole('button', { name: 'Add to stock' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Add to stock' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('This product is archived')
    expect(screen.getByRole('button', { name: 'Add to stock' })).toBeEnabled()
  })

  it('explains a failed read and offers a retry; explains an unconfigured server', async () => {
    const api = mockApi({
      ...base,
      'GET /api/v1/receipts/r1': receipt({ status: 'FAILED', extraction_error: 'NO_LINES', lines: [], line_count: 0 }),
      'POST /api/v1/receipts/r1/process': () => apiError(503, 'RECEIPT_AI_NOT_CONFIGURED', 'Receipt reading is not set up on this server yet.'),
    })
    renderWithProviders(<ReceiptReviewPage />, { path: '/inventory/receipts/r1', pattern: '/inventory/receipts/:receiptId' })
    expect(await screen.findByText(/No products were found on the photo/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Try reading again' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Receipt reading is not set up on this server yet.')
    expect(api.of('POST', '/api/v1/receipts/r1/process')).toHaveLength(1)
  })
})
