import { request } from '@/lib/api'

export interface Customer {
  id: string
  name: string
  phone: string | null
  notes: string | null
  credit_limit: string | null
  balance: string
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface CustomerCreate {
  name: string
  phone?: string | null
  notes?: string | null
  credit_limit?: string | null
}

export type LedgerEntryType = 'CHARGE' | 'REPAYMENT' | 'REVERSAL' | 'ADJUSTMENT'

export interface LedgerEntry {
  id: string
  entry_type: LedgerEntryType
  amount: string
  balance_after: string
  payment_method: 'CASH' | 'MPESA' | null
  reference: string | null
  reason: string | null
  sale_id: string | null
  occurred_at: string
  created_at: string
  created_by: string
}

export interface Ledger {
  customer_id: string
  balance: string
  credit_limit: string | null
  entries: LedgerEntry[]
}

export interface Debtor {
  customer_id: string
  name: string
  phone: string | null
  balance: string
  credit_limit: string | null
  oldest_unpaid_charge_at: string | null
}

export type CustomerListParams = { q?: string; include_archived?: boolean; limit?: number }

export const customersApi = {
  list: (params: CustomerListParams, signal?: AbortSignal) => request<Customer[]>('/api/v1/customers', { query: params, signal }),
  get: (id: string, signal?: AbortSignal) => request<Customer>(`/api/v1/customers/${id}`, { signal }),
  create: (body: CustomerCreate) => request<Customer>('/api/v1/customers', { method: 'POST', body }),
  ledger: (id: string, signal?: AbortSignal) => request<Ledger>(`/api/v1/customers/${id}/ledger`, { query: { limit: 100 }, signal }),
  repay: (id: string, body: { amount: string; payment_method: 'CASH' | 'MPESA'; reference?: string | null; allow_overpayment?: boolean }, idempotencyKey: string) =>
    request<LedgerEntry>(`/api/v1/customers/${id}/repayments`, { method: 'POST', body, headers: { 'Idempotency-Key': idempotencyKey } }),
  adjust: (id: string, body: { amount: string; direction: 'INCREASE' | 'DECREASE'; reason: string }, idempotencyKey: string) =>
    request<LedgerEntry>(`/api/v1/customers/${id}/adjustments`, { method: 'POST', body, headers: { 'Idempotency-Key': idempotencyKey } }),
  debtors: (sort: 'balance' | 'age', signal?: AbortSignal) => request<Debtor[]>('/api/v1/debtors', { query: { sort, limit: 200 }, signal }),
}
