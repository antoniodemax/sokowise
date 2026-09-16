import { useQuery } from '@tanstack/react-query'

import { queryKeys } from '@/lib/query-keys'

import { customersApi, type CustomerListParams } from './api'

export function useCustomers(params: CustomerListParams, enabled = true) {
  return useQuery({ queryKey: queryKeys.customers.list(params), queryFn: ({ signal }) => customersApi.list(params, signal), enabled })
}

export function useCustomer(id: string | undefined) {
  return useQuery({ queryKey: queryKeys.customers.detail(id ?? ''), queryFn: ({ signal }) => customersApi.get(id!, signal), enabled: !!id })
}

export function useLedger(id: string | undefined) {
  return useQuery({ queryKey: queryKeys.customers.ledger(id ?? ''), queryFn: ({ signal }) => customersApi.ledger(id!, signal), enabled: !!id })
}

export function useDebtors(sort: 'balance' | 'age', enabled = true) {
  return useQuery({ queryKey: queryKeys.customers.debtors({ sort }), queryFn: ({ signal }) => customersApi.debtors(sort, signal), enabled })
}
