import { request } from '@/lib/api'
import type { Session, SessionResponse } from '@/lib/session'

export interface LoginRequest {
  identifier: string
  password: string
}

export interface RegisterRequest {
  full_name: string
  phone: string
  email?: string | null
  password: string
  business_name: string
  business_type?: string
}

export interface ChangePasswordRequest {
  current_password: string
  new_password: string
}

export const BUSINESS_TYPES = [
  { value: 'GENERAL_SHOP', label: 'General shop / duka' },
  { value: 'BOUTIQUE', label: 'Boutique / clothing' },
  { value: 'SALON', label: 'Salon / barber' },
  { value: 'RESTAURANT', label: 'Restaurant / café' },
  { value: 'ELECTRONICS', label: 'Electronics / phones' },
  { value: 'OTHER', label: 'Other' },
] as const

export const authApi = {
  login: (body: LoginRequest) => request<SessionResponse>('/api/v1/auth/login', { method: 'POST', body, auth: false }),
  register: (body: RegisterRequest) => request<SessionResponse>('/api/v1/auth/register', { method: 'POST', body, auth: false }),
  logout: () => request<void>('/api/v1/auth/logout', { method: 'POST', auth: false, csrf: true }),
  logoutAll: () => request<void>('/api/v1/auth/logout-all', { method: 'POST' }),
  changePassword: (body: ChangePasswordRequest) => request<SessionResponse>('/api/v1/auth/change-password', { method: 'POST', body }),
  me: () => request<Session>('/api/v1/auth/me'),
}
