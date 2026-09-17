import { request } from '@/lib/api'
import { fetchCsv } from '@/lib/download'

export type ExpenseMethod = 'CASH' | 'MPESA'

export interface Expense {
  id: string
  amount: string
  category: string
  payment_method: ExpenseMethod
  reference: string | null
  note: string | null
  incurred_at: string
  deleted_at: string | null
  created_by: string
  created_at: string
  updated_at: string
}

export interface ExpenseWrite {
  amount: string
  category: string
  payment_method: ExpenseMethod
  reference?: string | null
  note?: string | null
  incurred_at?: string
}

export type ExpenseListParams = { date_from?: string; date_to?: string; category?: string; payment_method?: ExpenseMethod; include_deleted?: boolean; limit?: number }

export const expensesApi = {
  list: (params: ExpenseListParams, signal?: AbortSignal) => request<Expense[]>('/api/v1/expenses', { query: params, signal }),
  create: (body: ExpenseWrite) => request<Expense>('/api/v1/expenses', { method: 'POST', body }),
  update: (id: string, body: Partial<ExpenseWrite>) => request<Expense>(`/api/v1/expenses/${id}`, { method: 'PATCH', body }),
  remove: (id: string) => request<void>(`/api/v1/expenses/${id}`, { method: 'DELETE' }),
  categories: (signal?: AbortSignal) => request<{ suggested: string[] }>('/api/v1/expenses/categories', { signal }),
  exportCsv: (params: ExpenseListParams): Promise<Blob> => fetchCsv('/api/v1/expenses/export.csv', params, 'Could not export expenses.'),
}

export { saveBlob } from '@/lib/download'
