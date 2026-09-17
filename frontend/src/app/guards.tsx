import { Navigate, Outlet, useLocation } from 'react-router'

import { BrandMark } from '@/components/brand'
import { Spinner } from '@/components/ui/spinner'
import { useAuth } from '@/features/auth/auth-context'

function Restoring() {
  return (
    <div className="flex min-h-dvh flex-col items-center justify-center gap-4 bg-background">
      <BrandMark size={48} />
      <Spinner label="Restoring your session" />
    </div>
  )
}

/** Requires a session; sends users who must change their password to that screen first. */
export function RequireAuth() {
  const { session, restoring } = useAuth()
  const location = useLocation()
  if (restoring) return <Restoring />
  if (!session) return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />
  if (session.user.must_change_password && location.pathname !== '/change-password') {
    return <Navigate to="/change-password" replace />
  }
  return <Outlet />
}

/** Login/register: already signed in → straight into the app. */
export function RedirectIfAuthenticated() {
  const { session, restoring } = useAuth()
  if (restoring) return <Restoring />
  if (session) return <Navigate to={session.user.must_change_password ? '/change-password' : '/dashboard'} replace />
  return <Outlet />
}

/** Owner-only sections: staff see a friendly note rather than a backend 403. */
export function RequireOwner() {
  const { session } = useAuth()
  if (session?.role !== 'OWNER') {
    return (
      <div className="rounded-xl border border-border bg-card px-6 py-12 text-center">
        <h1 className="text-lg font-semibold">Owners only</h1>
        <p className="mt-1 text-sm text-muted-foreground">This section is available to the business owner.</p>
      </div>
    )
  }
  return <Outlet />
}
