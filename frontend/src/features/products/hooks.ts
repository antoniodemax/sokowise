import { useQuery } from '@tanstack/react-query'

import { queryKeys } from '@/lib/query-keys'

import { categoriesApi, productsApi, type ProductListParams } from './api'

export function useProducts(params: ProductListParams, enabled = true) {
  return useQuery({ queryKey: queryKeys.products.list(params), queryFn: ({ signal }) => productsApi.list(params, signal), enabled })
}

export function useProduct(id: string | undefined) {
  return useQuery({ queryKey: queryKeys.products.detail(id ?? ''), queryFn: ({ signal }) => productsApi.get(id!, signal), enabled: !!id })
}

export function useCategories() {
  return useQuery({ queryKey: queryKeys.categories.all, queryFn: ({ signal }) => categoriesApi.list(signal), staleTime: 5 * 60_000 })
}
