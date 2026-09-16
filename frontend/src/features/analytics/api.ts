import { request } from '@/lib/api'

import type { AnalyticsSummary } from '@/features/dashboard/api'

export type { AnalyticsSummary }
export type AnalyticsPeriod = 'today' | 'yesterday' | 'this_week' | 'this_month' | 'custom'
export type PeriodParams = { period: AnalyticsPeriod; date_from?: string; date_to?: string }
export type Granularity = 'day' | 'week' | 'month'

export interface TimeseriesBucket {
  bucket_start: string
  sales_count: number
  revenue: string
  discounts: string
  cogs: string
  lines_missing_cost: number
  gross_profit: string
  cash_collected: string
  expenses: string
  net_profit: string
}
export interface Timeseries {
  period: AnalyticsSummary['period']
  granularity: Granularity
  buckets: TimeseriesBucket[]
}
export interface ProductPerformance {
  product_id: string
  name: string
  is_active: boolean
  category_id: string | null
  quantity: string
  revenue: string
  cogs: string
  gross_profit: string
  sales_count: number
  lines_missing_cost: number
}
export interface SlowProduct {
  product_id: string
  name: string
  stock_quantity: string
  last_sold_at: string | null
}
export interface CategoryPerformance {
  category_id: string | null
  name: string | null
  quantity: string
  revenue: string
  cogs: string
  gross_profit: string
  lines_missing_cost: number
}
export interface ExpenseBreakdown {
  period: AnalyticsSummary['period']
  total: string
  count: number
  by_category: { key: string; total: string; count: number }[]
  by_method: Record<string, string>
}

export const analyticsApi = {
  summary: (p: PeriodParams, signal?: AbortSignal) => request<AnalyticsSummary>('/api/v1/analytics/summary', { query: p, signal }),
  timeseries: (p: PeriodParams & { granularity: Granularity }, signal?: AbortSignal) => request<Timeseries>('/api/v1/analytics/timeseries', { query: p, signal }),
  products: (p: PeriodParams & { sort: 'quantity' | 'revenue' | 'profit'; limit: number }, signal?: AbortSignal) => request<ProductPerformance[]>('/api/v1/analytics/products', { query: p, signal }),
  slowProducts: (days: number, signal?: AbortSignal) => request<SlowProduct[]>('/api/v1/analytics/slow-products', { query: { days, limit: 20 }, signal }),
  categories: (p: PeriodParams, signal?: AbortSignal) => request<CategoryPerformance[]>('/api/v1/analytics/categories', { query: p, signal }),
  expenses: (p: PeriodParams, signal?: AbortSignal) => request<ExpenseBreakdown>('/api/v1/analytics/expenses', { query: p, signal }),
}
