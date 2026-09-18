import { request } from '@/lib/api'

export interface PlatformTotals {
  businesses: number
  businesses_active: number
  users: number
  owners: number
  staff: number
  products: number
  customers: number
  sales: number
  revenue: string
  expenses: number
  credit_outstanding: string
  mpesa_messages: number
  receipts: number
  copilot_messages: number
  proposals_applied: number
}

export interface PlatformRecent {
  days: number
  new_businesses: number
  sales: number
  revenue: string
  businesses_with_sales: number
  users_signed_in: number
}

export interface SignupBucket {
  day: string
  businesses: number
}

/** One tenant as the operator sees it: name and counts only, never phones or money. */
export interface PlatformBusinessRow {
  id: string
  name: string
  business_type: string
  is_active: boolean
  created_at: string
  products: number
  sales: number
  last_sale_at: string | null
  last_login_at: string | null
}

export interface PlatformOverview {
  generated_at: string
  timezone: string
  totals: PlatformTotals
  last_7_days: PlatformRecent
  last_30_days: PlatformRecent
  signups_by_day: SignupBucket[]
  businesses: PlatformBusinessRow[]
}

export const adminApi = {
  overview: (signal?: AbortSignal) => request<PlatformOverview>('/api/v1/admin/overview', { signal }),
}
