import { useQuery } from '@tanstack/react-query'

import { queryKeys } from '@/lib/query-keys'

import { salesApi, type SaleListParams } from './api'

export function useSales(params: SaleListParams) {
  return useQuery({ queryKey: queryKeys.sales.list(params), queryFn: ({ signal }) => salesApi.list(params, signal) })
}

export function useSale(id: string | undefined) {
  return useQuery({ queryKey: queryKeys.sales.detail(id ?? ''), queryFn: ({ signal }) => salesApi.get(id!, signal), enabled: !!id })
}
