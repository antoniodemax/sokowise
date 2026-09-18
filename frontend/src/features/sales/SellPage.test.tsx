import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route } from 'react-router'
import { describe, expect, it } from 'vitest'

import { customer, product, sale, UUID_RE } from '@/test/fixtures'
import { apiError, json, mockApi, renderWithProviders, staffSession } from '@/test/render'

import SellPage from './SellPage'

const bread = product()
const milk = product({ id: 'p-milk', name: 'Milk', selling_price: '60.00', unit: 'litre' })

describe('SellPage', () => {
  it('adds items, auto-fills a cash tender and keeps one idempotency key across a retry', async () => {
    let attempts = 0
    const api = mockApi({
      'GET /api/v1/products': [bread, milk],
      'POST /api/v1/sales': () => (++attempts === 1 ? apiError(500, 'INTERNAL', 'boom') : json(sale(), 201)),
    })
    renderWithProviders(<SellPage />, { path: '/sales/new', pattern: '/sales/new' })
    expect(screen.getByRole('link', { name: 'Back to sales' })).toHaveAttribute('href', '/sales')
    await userEvent.click(await screen.findByRole('button', { name: /Bread/ }))
    await userEvent.click(screen.getByRole('button', { name: 'More Bread' }))
    expect(screen.getByLabelText('Amount (KSh)')).toHaveValue('110.00')
    expect(screen.getByText('Fully paid')).toBeInTheDocument()

    const submit = screen.getByRole('button', { name: 'Record sale · KSh 110' })
    await userEvent.click(submit)
    expect(await screen.findByRole('alert')).toHaveTextContent('Something went wrong on our side')
    await userEvent.click(screen.getByRole('button', { name: 'Record sale · KSh 110' }))
    await waitFor(() => expect(api.of('POST', '/api/v1/sales')).toHaveLength(2))

    const [first, second] = api.of('POST', '/api/v1/sales')
    expect(first.headers['Idempotency-Key']).toMatch(UUID_RE)
    expect(second.headers['Idempotency-Key']).toBe(first.headers['Idempotency-Key'])
    expect(first.body).toEqual({
      lines: [{ product_id: 'p-bread', quantity: '2', unit_price: '55.00' }],
      payments: [{ method: 'CASH', amount: '110.00', reference: null }],
      customer_id: null,
      discount_amount: '0',
      note: null,
    })
    // The cart is cleared for the next customer.
    expect(await screen.findByText('Search for a product above to start the sale.')).toBeInTheDocument()
  })

  it('requires a customer for credit and lets the owner override the credit limit with a fresh key', async () => {
    let attempts = 0
    const api = mockApi({
      'GET /api/v1/products': [bread],
      'GET /api/v1/customers': [customer()],
      'POST /api/v1/sales': () =>
        ++attempts === 1
          ? apiError(409, 'CREDIT_LIMIT_EXCEEDED', 'Credit limit exceeded', { balance: '100.00', credit_limit: '120.00', projected_balance: '155.00', owner_may_override: true })
          : json(sale({ customer_id: 'c-amina', payments: [{ id: 'pay', method: 'CREDIT', amount: '55.00', status: 'PENDING', reference: null, provider: null }] }), 201),
    })
    renderWithProviders(<SellPage />, { path: '/sales/new', pattern: '/sales/new' })
    await userEvent.click(await screen.findByRole('button', { name: /Bread/ }))
    await userEvent.selectOptions(screen.getByLabelText('Method'), 'CREDIT')
    expect(screen.getByText('Credit sales need a customer.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Record sale · KSh 55' })).toBeDisabled()

    await userEvent.click(screen.getByRole('button', { name: 'Add customer (needed for credit)' }))
    const dialog = await screen.findByRole('dialog', { name: 'Who is buying?' })
    await userEvent.click(await within(dialog).findByRole('button', { name: /Amina Njeri/ }))
    expect(await screen.findByText('This goes over their credit limit.')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Record sale · KSh 55' }))
    const confirm = await screen.findByRole('dialog', { name: 'Over the credit limit — allow anyway?' })
    expect(confirm).toHaveTextContent('would owe KSh 155')
    await userEvent.click(within(confirm).getByRole('button', { name: 'Allow this sale' }))
    await waitFor(() => expect(api.of('POST', '/api/v1/sales')).toHaveLength(2))

    const [first, second] = api.of('POST', '/api/v1/sales')
    expect(first.body).toMatchObject({ customer_id: 'c-amina', payments: [{ method: 'CREDIT', amount: '55.00' }] })
    expect(first.body).not.toHaveProperty('credit_limit_override')
    expect(second.body).toMatchObject({ credit_limit_override: true })
    expect(second.headers['Idempotency-Key']).not.toBe(first.headers['Idempotency-Key'])
  })

  it('tells staff to ask the owner when the credit limit blocks a sale, and hides backdating', async () => {
    mockApi({
      'GET /api/v1/products': [bread],
      'GET /api/v1/customers': [customer()],
      'POST /api/v1/sales': () => apiError(409, 'CREDIT_LIMIT_EXCEEDED', 'Credit limit exceeded', { balance: '100.00', credit_limit: '120.00', projected_balance: '155.00', owner_may_override: true }),
    })
    renderWithProviders(<SellPage />, { session: staffSession, path: '/sales/new', pattern: '/sales/new' })
    expect(screen.queryByLabelText(/Sold at/)).not.toBeInTheDocument()
    await userEvent.click(await screen.findByRole('button', { name: /Bread/ }))
    await userEvent.selectOptions(screen.getByLabelText('Method'), 'CREDIT')
    await userEvent.click(screen.getByRole('button', { name: 'Add customer (needed for credit)' }))
    await userEvent.click(await screen.findByRole('button', { name: /Amina Njeri/ }))
    await userEvent.click(await screen.findByRole('button', { name: 'Record sale · KSh 55' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Ask the owner to approve it')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('splits a payment between M-Pesa and cash and records the M-Pesa code as typed', async () => {
    const api = mockApi({ 'GET /api/v1/products': [bread], 'POST /api/v1/sales': () => json(sale(), 201) })
    renderWithProviders(<SellPage />, { path: '/sales/new', pattern: '/sales/new' })
    await userEvent.click(await screen.findByRole('button', { name: /Bread/ }))
    await userEvent.selectOptions(screen.getByLabelText('Method'), 'MPESA')
    const amount = screen.getByLabelText('Amount (KSh)')
    await userEvent.clear(amount)
    await userEvent.type(amount, '30')
    expect(screen.getByText('Still to pay')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Record sale · KSh 55' })).toBeDisabled()
    await userEvent.type(screen.getByLabelText(/M-Pesa code/), 'qgh7x2')
    await userEvent.click(screen.getByRole('button', { name: 'Cash' }))
    expect(screen.getByText('Fully paid')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Record sale · KSh 55' }))
    await waitFor(() => expect(api.of('POST', '/api/v1/sales')).toHaveLength(1))
    expect(api.of('POST', '/api/v1/sales')[0].body).toMatchObject({
      payments: [{ method: 'MPESA', amount: '30', reference: 'QGH7X2' }, { method: 'CASH', amount: '25.00', reference: null }],
    })
  })
})

describe('SellPage opened from an M-Pesa message', () => {
  it('prefills one M-Pesa tender with the amount and code, and returns to /mpesa after the sale', async () => {
    const api = mockApi({
      'GET /api/v1/products': [bread],
      'POST /api/v1/sales': () => json(sale({ total_amount: '110.00' }), 201),
    })
    renderWithProviders(<SellPage />, {
      path: '/sales/new?mpesa=m1&amount=110.00&code=RK1TEST001',
      pattern: '/sales/new',
      extraRoutes: <Route path="/mpesa" element={<h1>M-Pesa page</h1>} />,
    })
    expect(await screen.findByRole('status')).toHaveTextContent('From an M-Pesa message: KSh 110 received, code RK1TEST001')
    expect(screen.getByLabelText(/M-Pesa code/)).toHaveValue('RK1TEST001')
    expect(screen.getByLabelText('Amount (KSh)')).toHaveValue('110.00')
    await userEvent.click(await screen.findByRole('button', { name: /Bread/ }))
    await userEvent.click(screen.getByRole('button', { name: 'More Bread' }))
    await userEvent.click(screen.getByRole('button', { name: 'Record sale · KSh 110' }))
    await waitFor(() => expect(api.of('POST', '/api/v1/sales')).toHaveLength(1))
    expect((api.of('POST', '/api/v1/sales')[0].body as { payments: unknown[] }).payments).toEqual([{ method: 'MPESA', amount: '110.00', reference: 'RK1TEST001' }])
    expect(await screen.findByRole('heading', { name: 'M-Pesa page' })).toBeInTheDocument()
  })
})

describe('SellPage quick "Other item"', () => {
  it('does not offer "Other item" to staff when the product does not exist (staff cannot create products)', async () => {
    mockApi({ 'GET /api/v1/products': () => json([bread]) })
    renderWithProviders(<SellPage />, { session: staffSession, path: '/sales/new', pattern: '/sales/new' })
    expect(await screen.findByText('Bread')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Other item (no product)' })).not.toBeInTheDocument()
  })

  it('creates the untracked Other product on first use when the owner skipped the starter list', async () => {
    const created = product({ id: 'p-other', name: 'Other', selling_price: '0.00', track_inventory: false, unit: 'other' })
    const api = mockApi({
      'GET /api/v1/products': (_init: RequestInit, url: URL) => json(url.searchParams.get('q') === 'Other' ? [] : [bread]),
      'POST /api/v1/products': () => json(created, 201),
      'POST /api/v1/sales': () => json(sale({ total_amount: '50.00' }), 201),
    })
    renderWithProviders(<SellPage />, { path: '/sales/new', pattern: '/sales/new' })
    await userEvent.click(await screen.findByRole('button', { name: 'Other item (no product)' }))
    await userEvent.type(screen.getByLabelText('Other item amount'), '50')
    await userEvent.click(screen.getByRole('button', { name: 'Add' }))
    expect(await screen.findByText('Other')).toBeInTheDocument()
    expect(api.of('POST', '/api/v1/products')[0].body).toEqual({ name: 'Other', selling_price: '0.00', unit: 'other', track_inventory: false })
    await userEvent.click(screen.getByRole('button', { name: 'Record sale · KSh 50' }))
    await waitFor(() => expect(api.of('POST', '/api/v1/sales')).toHaveLength(1))
    expect((api.of('POST', '/api/v1/sales')[0].body as { lines: unknown[] }).lines).toEqual([{ product_id: 'p-other', quantity: '1', unit_price: '50' }])
  })

  it('adds a loose item as a line on the untracked Other product with the amount as its price', async () => {
    const other = product({ id: 'p-other', name: 'Other', selling_price: '0.00', track_inventory: false, unit: 'other' })
    const api = mockApi({
      'GET /api/v1/products': (_init: RequestInit, url: URL) => json(url.searchParams.get('q') === 'Other' ? [other] : [bread, other]),
      'POST /api/v1/sales': () => json(sale({ total_amount: '50.00' }), 201),
    })
    renderWithProviders(<SellPage />, { path: '/sales/new', pattern: '/sales/new' })
    await userEvent.click(await screen.findByRole('button', { name: 'Other item (no product)' }))
    await userEvent.type(screen.getByLabelText('Other item description'), '2 scoops rice')
    await userEvent.type(screen.getByLabelText('Other item amount'), '50')
    await userEvent.click(screen.getByRole('button', { name: 'Add' }))
    expect(screen.getByText('Other: 2 scoops rice')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Record sale · KSh 50' }))
    await waitFor(() => expect(api.of('POST', '/api/v1/sales')).toHaveLength(1))
    const body = api.of('POST', '/api/v1/sales')[0].body as { lines: unknown[]; note: string | null }
    expect(body.lines).toEqual([{ product_id: 'p-other', quantity: '1', unit_price: '50' }])
    expect(body.note).toBe('2 scoops rice')
  })
})
