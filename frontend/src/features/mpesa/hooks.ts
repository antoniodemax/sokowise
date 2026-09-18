import { useQuery } from '@tanstack/react-query'

import { queryKeys } from '@/lib/query-keys'

import { mpesaApi, type MpesaListParams } from './api'

export function useMpesaMessages(params: MpesaListParams) {
  return useQuery({ queryKey: queryKeys.mpesa.list(params), queryFn: ({ signal }) => mpesaApi.list(params, signal) })
}

export function useMpesaReconciliation(date: string) {
  return useQuery({ queryKey: queryKeys.mpesa.reconciliation(date), queryFn: ({ signal }) => mpesaApi.reconciliation(date, signal) })
}
