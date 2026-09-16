import { API_BASE_URL, ApiError, refreshSession, request } from '@/lib/api'
import { sessionStore } from '@/lib/session'

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
  /** The CSV needs the bearer header, so it is fetched and handed to the browser as a file. */
  exportCsv: async (params: ExpenseListParams): Promise<Blob> => {
    const url = new URL(`${API_BASE_URL}/api/v1/expenses/export.csv`, window.location.origin)
    for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== '') url.searchParams.set(k, String(v))
    const attempt = () => fetch(url, { headers: { Authorization: `Bearer ${sessionStore.getToken() ?? ''}` }, credentials: 'include' })
    let response = await attempt()
    if (response.status === 401 && (await refreshSession())) response = await attempt()
    if (!response.ok) {
      const body = (await response.json().catch(() => null)) as { error?: { code?: string; message?: string; details?: unknown; request_id?: string } } | null
      throw new ApiError(response.status, body?.error?.code ?? 'HTTP_ERROR', body?.error?.message ?? 'Could not export expenses.', body?.error?.details ?? null, body?.error?.request_id ?? null)
    }
    return response.blob()
  },
}

export function saveBlob(blob: Blob, filename: string) {
  const href = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = href
  a.download = filename
  document.body.append(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(href)
}
