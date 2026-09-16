import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { product } from '@/test/fixtures'
import { apiError, mockApi, renderWithProviders, staffSession } from '@/test/render'

import ProductsPage from './ProductsPage'

describe('ProductsPage', () => {
  it('lists products with stock badges and maps a duplicate-name conflict to the name field', async () => {
    const api = mockApi({
      'GET /api/v1/products': [product(), product({ id: 'p-2', name: 'Sugar 1kg', stock_quantity: '0.000' })],
      'GET /api/v1/categories': [],
      'POST /api/v1/products': () => apiError(409, 'PRODUCT_NAME_EXISTS', 'A product with this name already exists'),
    })
    renderWithProviders(<ProductsPage />, { path: '/products', pattern: '/products' })
    expect(await screen.findByText('Sugar 1kg')).toBeInTheDocument()
    expect(screen.getByText('In stock')).toBeInTheDocument()
    expect(screen.getByText('Out of stock')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Add product' }))
    const dialog = await screen.findByRole('dialog', { name: 'Add a product' })
    await userEvent.type(within(dialog).getByLabelText('Product name'), 'Bread')
    await userEvent.type(within(dialog).getByLabelText('Selling price (KSh)'), '55')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Add product' }))
    await waitFor(() => expect(api.of('POST', '/api/v1/products')).toHaveLength(1))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('already exists')
    expect(api.of('POST', '/api/v1/products')[0].body).toMatchObject({ name: 'Bread', selling_price: '55' })
  })

  it('hides catalogue writes from staff', async () => {
    mockApi({ 'GET /api/v1/products': [product()], 'GET /api/v1/categories': [] })
    renderWithProviders(<ProductsPage />, { session: staffSession, path: '/products', pattern: '/products' })
    expect(await screen.findByText('Bread')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Add product' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Categories' })).not.toBeInTheDocument()
  })
})
