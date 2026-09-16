import { useQuery } from '@tanstack/react-query'

import { queryKeys } from '@/lib/query-keys'

import { inventoryApi, type MovementParams } from './api'

export function useMovements(params: MovementParams, enabled = true) {
  return useQuery({ queryKey: queryKeys.inventory.movements(params), queryFn: ({ signal }) => inventoryApi.movements(params, signal), enabled })
}

export function useLowStock(enabled = true) {
  return useQuery({ queryKey: queryKeys.inventory.lowStock, queryFn: ({ signal }) => inventoryApi.lowStock(signal), enabled })
}
