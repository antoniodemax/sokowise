import { API_BASE_URL, ApiError, refreshSession, request } from '@/lib/api'
import { sessionStore } from '@/lib/session'

export type ReceiptStatus = 'UPLOADED' | 'PROCESSING' | 'READY_FOR_REVIEW' | 'CONFIRMED' | 'FAILED' | 'CANCELLED'
export type MatchStatus = 'MATCHED' | 'AMBIGUOUS' | 'UNMATCHED'
export type LineReview = 'PENDING' | 'APPLIED' | 'SKIPPED'

export interface ReceiptLine {
  id: string
  position: number
  extracted_name: string
  extracted_sku: string | null
  extracted_quantity: string
  extracted_unit_cost: string
  extracted_line_total: string | null
  confidence: string | null
  warnings: string[]
  match_status: MatchStatus
  matched_product_id: string | null
  candidate_product_ids: string[]
  review_status: LineReview
  final_product_id: string | null
  final_quantity: string | null
  final_unit_cost: string | null
  movement_id: string | null
}

export interface ReceiptSummary {
  id: string
  status: ReceiptStatus
  original_filename: string | null
  mime_type: string
  size_bytes: number
  supplier_name: string | null
  receipt_number: string | null
  receipt_date: string | null
  currency: string | null
  extracted_subtotal: string | null
  extracted_total: string | null
  extraction_provider: string | null
  extraction_model: string | null
  extraction_error: string | null
  warnings: string[]
  line_count: number
  extracted_at: string | null
  confirmed_at: string | null
  created_at: string
  updated_at: string
}

export interface Receipt extends ReceiptSummary {
  lines: ReceiptLine[]
}

export interface ConfirmLine {
  line_id: string
  product_id: string
  quantity: string
  unit_cost: string
  update_cost_price: boolean
}

export interface ConfirmResult {
  receipt: Receipt
  movements_created: number
}

/** Mirrors the backend limits (RECEIPT_MAX_BYTES default 8 MB; JPEG, PNG or WebP). */
export const MAX_RECEIPT_BYTES = 8 * 1024 * 1024
export const ACCEPTED_TYPES = ['image/jpeg', 'image/png', 'image/webp']

export const receiptsApi = {
  list: (signal?: AbortSignal) => request<ReceiptSummary[]>('/api/v1/receipts', { signal }),
  get: (id: string, signal?: AbortSignal) => request<Receipt>(`/api/v1/receipts/${id}`, { signal }),
  process: (id: string) => request<Receipt>(`/api/v1/receipts/${id}/process`, { method: 'POST' }),
  confirm: (id: string, body: { lines: ConfirmLine[]; supplier_name?: string | null; reason?: string | null }) =>
    request<ConfirmResult>(`/api/v1/receipts/${id}/confirm`, { method: 'POST', body }),
  cancel: (id: string) => request<Receipt>(`/api/v1/receipts/${id}/cancel`, { method: 'POST' }),
  /** Multipart upload; the shared client only speaks JSON, so this is the one hand-rolled fetch. */
  upload: async (file: File): Promise<Receipt> => {
    const form = new FormData()
    form.append('file', file, file.name)
    const attempt = () =>
      fetch(`${API_BASE_URL}/api/v1/receipts`, {
        method: 'POST',
        body: form,
        headers: { Authorization: `Bearer ${sessionStore.getToken() ?? ''}` },
        credentials: 'include',
      })
    let response: Response
    try {
      response = await attempt()
      if (response.status === 401 && (await refreshSession())) response = await attempt()
    } catch {
      throw ApiError.network()
    }
    if (!response.ok) {
      const body = (await response.json().catch(() => null)) as { error?: { code?: string; message?: string; details?: unknown; request_id?: string } } | null
      throw new ApiError(response.status, body?.error?.code ?? 'HTTP_ERROR', body?.error?.message ?? 'The upload failed.', body?.error?.details ?? null, body?.error?.request_id ?? null)
    }
    return (await response.json()) as Receipt
  },
  imageUrl: (id: string) => `${API_BASE_URL}/api/v1/receipts/${id}/image`,
}
