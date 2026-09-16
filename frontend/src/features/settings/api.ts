import { request } from '@/lib/api'
import type { Role } from '@/lib/session'

export interface BusinessSettings {
  staff_can_restock?: boolean
  sale_backdate_days?: number
  low_stock_default_threshold?: number
}

export interface Business {
  id: string
  name: string
  business_type: string
  phone: string | null
  address: string | null
  currency: string
  timezone: string
  settings: BusinessSettings
  is_active: boolean
  created_at: string
}

export interface BusinessUpdate {
  name?: string
  business_type?: string
  phone?: string | null
  address?: string | null
  timezone?: string
  settings?: BusinessSettings
}

export interface Member {
  user_id: string
  full_name: string
  phone: string
  email: string | null
  role: Role
  is_active: boolean
  must_change_password: boolean
  last_login_at: string | null
  joined_at: string
}

export interface StaffCreate {
  full_name: string
  phone: string
  email?: string | null
  password: string
}

export const businessApi = {
  get: (signal?: AbortSignal) => request<Business>('/api/v1/business', { signal }),
  update: (body: BusinessUpdate) => request<Business>('/api/v1/business', { method: 'PATCH', body }),
}

export const membersApi = {
  list: (signal?: AbortSignal) => request<Member[]>('/api/v1/users', { signal }),
  create: (body: StaffCreate) => request<Member>('/api/v1/users', { method: 'POST', body }),
  update: (userId: string, body: { role?: Role; is_active?: boolean }) => request<Member>(`/api/v1/users/${userId}`, { method: 'PATCH', body }),
  resetPassword: (userId: string, password: string) => request<Member>(`/api/v1/users/${userId}/reset-password`, { method: 'POST', body: { password } }),
}
