import { request } from '@/lib/api'

export const PRODUCT_UNITS = ['piece', 'kg', 'g', 'litre', 'ml', 'metre', 'pack', 'service', 'other'] as const
export type ProductUnit = (typeof PRODUCT_UNITS)[number]

export interface Product {
  id: string
  name: string
  category_id: string | null
  sku: string | null
  barcode: string | null
  unit: ProductUnit
  selling_price: string
  cost_price: string | null
  track_inventory: boolean
  stock_quantity: string
  low_stock_threshold: string | null
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface Category {
  id: string
  name: string
  created_at: string
  updated_at: string
}

export interface ProductCreate {
  name: string
  category_id?: string | null
  sku?: string | null
  barcode?: string | null
  unit?: ProductUnit
  selling_price: string
  cost_price?: string | null
  track_inventory?: boolean
  low_stock_threshold?: string | null
  opening_stock?: string | null
  opening_unit_cost?: string | null
}

export type ProductUpdate = Partial<Omit<ProductCreate, 'opening_stock' | 'opening_unit_cost'>> & { is_active?: boolean }

export type ProductListParams = {
  q?: string
  category_id?: string
  include_archived?: boolean
  limit?: number
}

export const productsApi = {
  list: (params: ProductListParams, signal?: AbortSignal) => request<Product[]>('/api/v1/products', { query: params, signal }),
  get: (id: string, signal?: AbortSignal) => request<Product>(`/api/v1/products/${id}`, { signal }),
  create: (body: ProductCreate) => request<Product>('/api/v1/products', { method: 'POST', body }),
  update: (id: string, body: ProductUpdate) => request<Product>(`/api/v1/products/${id}`, { method: 'PATCH', body }),
}

export const categoriesApi = {
  list: (signal?: AbortSignal) => request<Category[]>('/api/v1/categories', { signal }),
  create: (name: string) => request<Category>('/api/v1/categories', { method: 'POST', body: { name } }),
  rename: (id: string, name: string) => request<Category>(`/api/v1/categories/${id}`, { method: 'PATCH', body: { name } }),
  remove: (id: string) => request<void>(`/api/v1/categories/${id}`, { method: 'DELETE' }),
}
