import { request } from '@/lib/api'

export type MpesaStatus = 'UNPARSED' | 'UNMATCHED' | 'MATCHED' | 'IGNORED'
export type SmsKind = 'POCHI' | 'TILL' | 'PAYBILL' | 'SEND_MONEY' | 'UNKNOWN'

export interface CandidatePayment {
  payment_id: string
  sale_id: string
  amount: string
  reference: string | null
  sold_at: string
}

export interface CandidateCustomer {
  customer_id: string
  name: string
  phone: string | null
  balance: string
}

export interface MpesaMessage {
  id: string
  status: MpesaStatus
  code: string | null
  amount: string | null
  kind: SmsKind | null
  sender_name: string | null
  sender_phone_masked: string | null
  account_reference: string | null
  occurred_at: string | null
  raw_text: string
  payment_id: string | null
  sale_id: string | null
  credit_transaction_id: string | null
  customer_id: string | null
  matched_at: string | null
  ignored_at: string | null
  ignore_reason: string | null
  created_at: string
  candidates: { payments: CandidatePayment[]; customers: CandidateCustomer[] } | null
}

export interface Reconciliation {
  date: string
  received_count: number
  received_total: string
  matched_count: number
  matched_total: string
  unmatched_count: number
  unmatched_total: string
  ignored_count: number
  unparsed_count: number
  recorded_in_app: string
}

export type MpesaListParams = { status?: MpesaStatus; date_from?: string; date_to?: string; limit?: number }

export const mpesaApi = {
  paste: (text: string) => request<MpesaMessage>('/api/v1/mpesa/messages', { method: 'POST', body: { text } }),
  list: (params: MpesaListParams, signal?: AbortSignal) => request<MpesaMessage[]>('/api/v1/mpesa/messages', { query: params, signal }),
  get: (id: string, signal?: AbortSignal) => request<MpesaMessage>(`/api/v1/mpesa/messages/${id}`, { signal }),
  reconciliation: (date: string, signal?: AbortSignal) => request<Reconciliation>('/api/v1/mpesa/reconciliation', { query: { date }, signal }),
  match: (id: string, body: { payment_id: string } | { credit_transaction_id: string }) =>
    request<MpesaMessage>(`/api/v1/mpesa/messages/${id}/match`, { method: 'POST', body }),
  repayment: (id: string, body: { customer_id: string; allow_overpayment?: boolean }) =>
    request<MpesaMessage>(`/api/v1/mpesa/messages/${id}/repayment`, { method: 'POST', body }),
  ignore: (id: string, reason?: string) => request<MpesaMessage>(`/api/v1/mpesa/messages/${id}/ignore`, { method: 'POST', body: { reason: reason ?? null } }),
}
