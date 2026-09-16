import type { Customer, LedgerEntry } from '@/features/customers/api'
import type { Expense } from '@/features/expenses/api'
import type { Product } from '@/features/products/api'
import type { Sale } from '@/features/sales/api'

export function product(overrides: Partial<Product> = {}): Product {
  return {
    id: 'p-bread',
    name: 'Bread',
    category_id: null,
    sku: null,
    barcode: null,
    unit: 'piece',
    selling_price: '55.00',
    cost_price: '40.00',
    track_inventory: true,
    stock_quantity: '10.000',
    low_stock_threshold: '5.000',
    is_active: true,
    created_at: '2026-09-01T06:00:00Z',
    updated_at: '2026-09-01T06:00:00Z',
    ...overrides,
  }
}

export function customer(overrides: Partial<Customer> = {}): Customer {
  return {
    id: 'c-amina',
    name: 'Amina Njeri',
    phone: '+254711000111',
    notes: null,
    credit_limit: '120.00',
    balance: '100.00',
    is_active: true,
    created_at: '2026-09-01T06:00:00Z',
    updated_at: '2026-09-01T06:00:00Z',
    ...overrides,
  }
}

export function ledgerEntry(overrides: Partial<LedgerEntry> = {}): LedgerEntry {
  return {
    id: 'le-1',
    entry_type: 'CHARGE',
    amount: '100.00',
    balance_after: '100.00',
    payment_method: null,
    reference: null,
    reason: null,
    sale_id: 's-1',
    occurred_at: '2026-09-10T08:30:00Z',
    created_at: '2026-09-10T08:30:00Z',
    created_by: 'u-owner',
    ...overrides,
  }
}

export function sale(overrides: Partial<Sale> = {}): Sale {
  return {
    id: 's-1',
    status: 'COMPLETED',
    customer_id: null,
    subtotal: '110.00',
    discount_amount: '0.00',
    total_amount: '110.00',
    note: null,
    sold_at: '2026-09-15T09:15:00Z',
    created_by: 'u-owner',
    created_at: '2026-09-15T09:15:00Z',
    voided_at: null,
    voided_by: null,
    void_reason: null,
    items: [{ id: 'si-1', product_id: 'p-bread', product_name: 'Bread', quantity: '2.000', unit_price: '55.00', default_unit_price: '55.00', line_total: '110.00', discount_allocated: '0.00' }],
    payments: [{ id: 'pay-1', method: 'CASH', amount: '110.00', status: 'CONFIRMED', reference: null, provider: null }],
    ...overrides,
  }
}

export function expense(overrides: Partial<Expense> = {}): Expense {
  return {
    id: 'e-1',
    amount: '1500.00',
    category: 'RENT',
    payment_method: 'CASH',
    reference: null,
    note: null,
    incurred_at: '2026-09-01T07:00:00Z',
    deleted_at: null,
    created_by: 'u-owner',
    created_at: '2026-09-01T07:00:00Z',
    updated_at: '2026-09-01T07:00:00Z',
    ...overrides,
  }
}

export const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
