import { request } from '@/lib/api'

export type MovementType = 'INITIAL' | 'RESTOCK' | 'SALE' | 'SALE_REVERSAL' | 'ADJUSTMENT'

export interface Movement {
  id: string
  product_id: string
  movement_type: MovementType
  quantity_delta: string
  quantity_after: string
  unit_cost: string | null
  total_cost: string | null
  sale_id: string | null
  supplier_name: string | null
  reason: string | null
  occurred_at: string
  created_at: string
  created_by: string
}

export interface LowStockProduct {
  product_id: string
  name: string
  sku: string | null
  unit: string
  stock_quantity: string
  threshold: string
}

export type MovementParams = {
  product_id?: string
  movement_type?: MovementType
  date_from?: string
  date_to?: string
  limit?: number
}

export const inventoryApi = {
  movements: (params: MovementParams, signal?: AbortSignal) => request<Movement[]>('/api/v1/inventory/movements', { query: params, signal }),
  lowStock: (signal?: AbortSignal) => request<LowStockProduct[]>('/api/v1/inventory/low-stock', { query: { limit: 100 }, signal }),
  restock: (body: { product_id: string; quantity: string; unit_cost: string; supplier_name?: string | null; reason?: string | null; update_cost_price?: boolean }) =>
    request<Movement>('/api/v1/inventory/restock', { method: 'POST', body }),
  adjust: (body: { product_id: string; quantity_delta: string; reason: string }) => request<Movement>('/api/v1/inventory/adjust', { method: 'POST', body }),
  initial: (body: { product_id: string; quantity: string; unit_cost: string }) => request<Movement>('/api/v1/inventory/initial', { method: 'POST', body }),
}

export const MOVEMENT_LABELS: Record<MovementType, string> = {
  INITIAL: 'Opening stock',
  RESTOCK: 'Restock',
  SALE: 'Sale',
  SALE_REVERSAL: 'Sale voided',
  ADJUSTMENT: 'Adjustment',
}
