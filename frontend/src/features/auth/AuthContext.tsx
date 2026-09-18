import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'

import { refreshSession } from '@/lib/api'
import { sessionStore, type Session, type SessionResponse } from '@/lib/session'

import { authApi, isGoogleSignupPending, type ChangePasswordRequest, type GoogleRegisterRequest, type LoginRequest, type RegisterRequest } from './api'

import { AuthContext, type AuthContextValue } from './auth-context'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(sessionStore.get())
  const [restoring, setRestoring] = useState(true)

  useEffect(() => sessionStore.subscribe(setSession), [])

  useEffect(() => {
    // A reload has no access token in memory; the HttpOnly cookie may still be valid.
    let cancelled = false
    refreshSession().finally(() => {
      if (!cancelled) setRestoring(false)
    })
    return () => {
      cancelled = true
    }
  }, [])

  const adopt = useCallback((response: SessionResponse) => sessionStore.set(response), [])

  const login = useCallback(async (body: LoginRequest) => adopt(await authApi.login(body)), [adopt])
  const register = useCallback(async (body: RegisterRequest) => adopt(await authApi.register(body)), [adopt])
  const changePassword = useCallback(async (body: ChangePasswordRequest) => adopt(await authApi.changePassword(body)), [adopt])
  const signInWithGoogle = useCallback(
    async (credential: string) => {
      const response = await authApi.googleSignIn(credential)
      return isGoogleSignupPending(response) ? response : adopt(response)
    },
    [adopt],
  )
  const registerWithGoogle = useCallback(async (body: GoogleRegisterRequest) => adopt(await authApi.googleRegister(body)), [adopt])
  const logout = useCallback(async () => {
    try {
      await authApi.logout()
    } finally {
      sessionStore.clear()
    }
  }, [])
  const logoutAll = useCallback(async () => {
    try {
      await authApi.logoutAll()
    } finally {
      sessionStore.clear()
    }
  }, [])

  const value = useMemo<AuthContextValue>(
    () => ({ session, restoring, login, register, changePassword, signInWithGoogle, registerWithGoogle, logout, logoutAll }),
    [session, restoring, login, register, changePassword, signInWithGoogle, registerWithGoogle, logout, logoutAll],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
