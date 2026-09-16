import { request } from '@/lib/api'

export type DashboardPeriod = 'today' | 'yesterday' | 'this_week' | 'this_month'

/** GET /api/v1/analytics/summary (docs/ARCHITECTURE.md §5.11, §5.12). */
export interface AnalyticsSummary {
  period: { timezone: string; date_from: string; date_to: string }
  sales_count: number
  revenue: string
  discounts: string
  cogs: string
  lines_missing_cost: number
  products_missing_cost: number
  gross_profit: string
  expenses: string
  net_profit: string
  tender_split: Record<string, string>
  cash_collected: Record<string, string>
  cash_collected_total: string
  receivables_outstanding: string
}

export const dashboardApi = {
  summary: (period: DashboardPeriod, signal?: AbortSignal) =>
    request<AnalyticsSummary>('/api/v1/analytics/summary', { query: { period }, signal }),
}
