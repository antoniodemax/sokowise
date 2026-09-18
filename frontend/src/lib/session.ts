/**
 * The in-memory session. The access token lives here and nowhere else (never
 * localStorage); the refresh token is an HttpOnly cookie the browser sends to
 * /api/v1/auth on its own. A reload therefore starts with no token and asks the
 * backend to refresh (docs/ARCHITECTURE.md §5.1).
 */

export type Role = 'OWNER' | 'STAFF'

export interface SessionUser {
  id: string
  full_name: string
  phone: string
  email: string | null
  must_change_password: boolean
}

export interface SessionBusiness {
  id: string
  name: string
  business_type: string
  currency: string
  timezone: string
  is_active: boolean
}

/** What login, register, refresh and change-password return. */
export interface SessionResponse {
  access_token: string
  token_type: 'bearer'
  expires_in: number
  user: SessionUser
  business: SessionBusiness
  role: Role
  /** Operator dashboard access (PLATFORM_ADMIN_PHONES / PLATFORM_ADMIN_EMAILS on the server). Only hides the route; the backend re-checks. */
  is_platform_admin?: boolean
}

export interface Session {
  user: SessionUser
  business: SessionBusiness
  role: Role
  is_platform_admin: boolean
}

type Listener = (session: Session | null) => void

let accessToken: string | null = null
let current: Session | null = null
const listeners = new Set<Listener>()

export const sessionStore = {
  getToken: (): string | null => accessToken,
  get: (): Session | null => current,
  set(response: SessionResponse): Session {
    accessToken = response.access_token
    current = { user: response.user, business: response.business, role: response.role, is_platform_admin: response.is_platform_admin === true }
    listeners.forEach((listener) => listener(current))
    return current
  },
  /** Reflect an edited business profile without a new login (the token is unchanged). */
  updateBusiness(patch: Partial<SessionBusiness>): void {
    if (!current) return
    current = { ...current, business: { ...current.business, ...patch } }
    listeners.forEach((listener) => listener(current))
  },
  clear(): void {
    accessToken = null
    current = null
    listeners.forEach((listener) => listener(null))
  },
  subscribe(listener: Listener): () => void {
    listeners.add(listener)
    return () => listeners.delete(listener)
  },
}
