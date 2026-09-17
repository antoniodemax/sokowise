import { useQuery } from '@tanstack/react-query'

import { receiptsApi } from './api'

export const receiptKeys = {
  all: ['receipts'] as const,
  list: ['receipts', 'list'] as const,
  detail: (id: string) => ['receipts', 'detail', id] as const,
}

export function useReceipts() {
  return useQuery({ queryKey: receiptKeys.list, queryFn: ({ signal }) => receiptsApi.list(signal) })
}

export function useReceipt(id: string | undefined) {
  return useQuery({ queryKey: receiptKeys.detail(id ?? ''), queryFn: ({ signal }) => receiptsApi.get(id!, signal), enabled: !!id })
}
