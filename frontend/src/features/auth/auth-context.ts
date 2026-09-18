import { createContext, useContext } from 'react'

import type { Session } from '@/lib/session'

import type { ChangePasswordRequest, GoogleRegisterRequest, GoogleSignupPending, LoginRequest, RegisterRequest } from './api'

export interface AuthContextValue {
  session: Session | null
  /** True until the first refresh attempt on page load has settled. */
  restoring: boolean
  login: (body: LoginRequest) => Promise<Session>
  register: (body: RegisterRequest) => Promise<Session>
  changePassword: (body: ChangePasswordRequest) => Promise<Session>
  /** A session when the Google account is known, or the pending sign-up to finish. */
  signInWithGoogle: (credential: string) => Promise<Session | GoogleSignupPending>
  registerWithGoogle: (body: GoogleRegisterRequest) => Promise<Session>
  logout: () => Promise<void>
  logoutAll: () => Promise<void>
}

export const AuthContext = createContext<AuthContextValue | null>(null)

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth must be used inside AuthProvider')
  return value
}
