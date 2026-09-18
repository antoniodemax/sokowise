import { Outlet } from 'react-router'

import { BrandLockup } from '@/components/brand'

/** Centred card on the brand background for login, register and password change. */
export function AuthLayout() {
  return (
    <div className="flex min-h-dvh flex-col bg-background">
      <div className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center px-4 py-8 sm:py-12">
        <div className="anim-rise rounded-xl border border-border bg-card p-6 shadow-sm sm:p-8">
          <div className="mb-6 flex justify-center border-b border-border pb-6">
            <BrandLockup className="w-60 sm:w-64" />
          </div>
          <Outlet />
        </div>
        <p className="mt-6 text-center text-xs text-muted-foreground">Sales, stock, customer credit and expenses — for Kenyan small businesses.</p>
      </div>
    </div>
  )
}
