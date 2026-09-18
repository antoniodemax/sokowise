import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router'

import { Alert } from '@/components/ui/alert'
import { describeError } from '@/lib/errors'

import { isGoogleSignupPending } from './api'
import { useAuth } from './auth-context'

import { GOOGLE_CLIENT_ID } from './google-config'

const GSI_SRC = 'https://accounts.google.com/gsi/client'

interface GoogleAccounts {
  id: {
    initialize: (config: { client_id: string; callback: (response: { credential: string }) => void; ux_mode?: 'popup'; auto_select?: boolean }) => void
    renderButton: (parent: HTMLElement, options: Record<string, string | number>) => void
  }
}
declare global {
  interface Window {
    google?: { accounts: GoogleAccounts }
  }
}

let gsiLoading: Promise<void> | null = null
function loadGsi(): Promise<void> {
  if (window.google?.accounts) return Promise.resolve()
  if (gsiLoading) return gsiLoading
  gsiLoading = new Promise<void>((resolve, reject) => {
    const script = document.createElement('script')
    script.src = GSI_SRC
    script.async = true
    script.defer = true
    script.onload = () => resolve()
    script.onerror = () => { gsiLoading = null; reject(new Error('Google sign-in could not load')) }
    document.head.appendChild(script)
  })
  return gsiLoading
}

/**
 * "Continue with Google" via Google Identity Services. Google hands the browser an ID token;
 * the backend verifies it and either opens a session or asks for the finish-up form
 * (phone, business). Hidden when no client id is configured.
 */
export function GoogleButton({ label = 'signin_with' }: { label?: 'signin_with' | 'signup_with' | 'continue_with' }) {
  const { signInWithGoogle } = useAuth()
  const navigate = useNavigate()
  const host = useRef<HTMLDivElement>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!GOOGLE_CLIENT_ID || !host.current) return
    let cancelled = false
    loadGsi()
      .then(() => {
        if (cancelled || !host.current || !window.google) return
        window.google.accounts.id.initialize({
          client_id: GOOGLE_CLIENT_ID,
          ux_mode: 'popup',
          callback: ({ credential }) => {
            setBusy(true)
            setError(null)
            signInWithGoogle(credential)
              .then((result) => {
                if (isGoogleSignupPending(result)) navigate('/register/google', { state: result })
                else navigate(result.user.must_change_password ? '/change-password' : '/dashboard', { replace: true })
              })
              .catch((e: unknown) => setError(describeError(e)))
              .finally(() => setBusy(false))
          },
        })
        window.google.accounts.id.renderButton(host.current, { theme: 'outline', size: 'large', shape: 'pill', text: label, width: 320 })
      })
      .catch((e: unknown) => setError(describeError(e)))
    return () => { cancelled = true }
  }, [label, navigate, signInWithGoogle])

  if (!GOOGLE_CLIENT_ID) return null
  return (
    <div className="mt-6 space-y-3">
      <div className="flex items-center gap-3 text-xs text-muted-foreground" aria-hidden="true">
        <span className="h-px flex-1 bg-border" />or<span className="h-px flex-1 bg-border" />
      </div>
      <div ref={host} className="flex justify-center" aria-busy={busy} data-testid="google-button" />
      {error && <Alert variant="destructive" role="alert">{error}</Alert>}
    </div>
  )
}
