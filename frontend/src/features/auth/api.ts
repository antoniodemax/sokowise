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

export interface GoogleRegisterRequest {
  registration_token: string
  phone: string
  full_name?: string | null
  business_name: string
  business_type?: string
}

/** POST /auth/google: a session, or a pending sign-up that needs the finish-up form. */
export interface GoogleSignupPending {
  status: 'needs_registration'
  registration_token: string
  email: string
  name: string | null
}
export type GoogleSignInResponse = SessionResponse | GoogleSignupPending

export function isGoogleSignupPending(response: object): response is GoogleSignupPending {
  return 'status' in response && (response as { status?: unknown }).status === 'needs_registration'
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
  googleSignIn: (credential: string) => request<GoogleSignInResponse>('/api/v1/auth/google', { method: 'POST', body: { credential }, auth: false }),
  googleRegister: (body: GoogleRegisterRequest) => request<SessionResponse>('/api/v1/auth/google/register', { method: 'POST', body, auth: false }),
  requestPasswordReset: (phone: string) => request<{ message: string }>('/api/v1/auth/password-reset/request', { method: 'POST', body: { phone }, auth: false }),
  confirmPasswordReset: (body: { phone: string; code: string; new_password: string }) => request<{ message: string }>('/api/v1/auth/password-reset/confirm', { method: 'POST', body, auth: false }),
  me: () => request<Session>('/api/v1/auth/me'),
}
