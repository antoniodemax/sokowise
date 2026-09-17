import { request } from '@/lib/api'
import { fetchCsv } from '@/lib/download'

export type PaymentMethod = 'CASH' | 'MPESA' | 'CREDIT'
export type SaleStatus = 'COMPLETED' | 'VOIDED'

export interface SaleItem {
  id: string
  product_id: string
  product_name: string
  quantity: string
  unit_price: string
  default_unit_price: string | null
  line_total: string
  discount_allocated: string
}

export interface SalePayment {
  id: string
  method: PaymentMethod
  amount: string
  status: string
  reference: string | null
  provider: string | null
}

export interface Sale {
  id: string
  status: SaleStatus
  customer_id: string | null
  subtotal: string
  discount_amount: string
  total_amount: string
  note: string | null
  sold_at: string
  created_by: string
  created_at: string
  voided_at: string | null
  voided_by: string | null
  void_reason: string | null
  items: SaleItem[]
  payments: SalePayment[]
}

export interface SaleCreate {
  lines: { product_id: string; quantity: string; unit_price?: string }[]
  payments: { method: PaymentMethod; amount: string; reference?: string | null }[]
  customer_id?: string | null
  discount_amount?: string
  note?: string | null
  sold_at?: string
  credit_limit_override?: boolean
}

/** `date_from`/`date_to` are ISO instants: sold_at >= date_from and < date_to. */
export type SaleListParams = { date_from?: string; date_to?: string; customer_id?: string; limit?: number }

export const PAYMENT_LABELS: Record<PaymentMethod, string> = { CASH: 'Cash', MPESA: 'M-Pesa', CREDIT: 'Credit' }

export const salesApi = {
  create: (body: SaleCreate, idempotencyKey: string) =>
    request<Sale>('/api/v1/sales', { method: 'POST', body, headers: { 'Idempotency-Key': idempotencyKey } }),
  list: (params: SaleListParams, signal?: AbortSignal) => request<Sale[]>('/api/v1/sales', { query: params, signal }),
  get: (id: string, signal?: AbortSignal) => request<Sale>(`/api/v1/sales/${id}`, { signal }),
  void: (id: string, reason: string) => request<Sale>(`/api/v1/sales/${id}/void`, { method: 'POST', body: { reason } }),
  /** OWNER only: one CSV row per sale line, local dates (PRD NFR-12). */
  exportCsv: (params: { date_from?: string; date_to?: string }): Promise<Blob> => fetchCsv('/api/v1/sales/export.csv', params, 'Could not export sales.'),
}
