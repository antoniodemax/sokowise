import { lazy, Suspense } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router'

import { Spinner } from '@/components/ui/spinner'

import { RedirectIfAuthenticated, RequireAuth, RequireOwner } from './guards'
import { AppShell } from './layouts/AppShell'
import { AuthLayout } from './layouts/AuthLayout'

const LoginPage = lazy(() => import('@/features/auth/LoginPage'))
const RegisterPage = lazy(() => import('@/features/auth/RegisterPage'))
const ChangePasswordPage = lazy(() => import('@/features/auth/ChangePasswordPage'))
const DashboardPage = lazy(() => import('@/features/dashboard/DashboardPage'))
const SettingsPage = lazy(() => import('@/features/settings/SettingsPage'))
const ComingSoonPage = lazy(() => import('@/features/placeholders/ComingSoonPage'))
const NotFoundPage = lazy(() => import('@/features/placeholders/NotFoundPage'))

function PageFallback() {
  return (
    <div className="flex justify-center py-16">
      <Spinner />
    </div>
  )
}

export function AppRouter() {
  return (
    <BrowserRouter>
      <Suspense fallback={<PageFallback />}>
        <Routes>
          <Route element={<RedirectIfAuthenticated />}>
            <Route element={<AuthLayout />}>
              <Route path="/login" element={<LoginPage />} />
              <Route path="/register" element={<RegisterPage />} />
            </Route>
          </Route>
          <Route element={<RequireAuth />}>
            <Route element={<AuthLayout />}>
              <Route path="/change-password" element={<ChangePasswordPage />} />
            </Route>
            <Route element={<AppShell />}>
              <Route index element={<DashboardPage />} />
              <Route path="/sales" element={<ComingSoonPage section="Sales" />} />
              <Route path="/products" element={<ComingSoonPage section="Products" />} />
              <Route path="/inventory" element={<ComingSoonPage section="Inventory" />} />
              <Route path="/customers" element={<ComingSoonPage section="Customers" />} />
              <Route element={<RequireOwner />}>
                <Route path="/expenses" element={<ComingSoonPage section="Expenses" />} />
                <Route path="/analytics" element={<ComingSoonPage section="Analytics" />} />
              </Route>
              <Route path="/settings" element={<SettingsPage />} />
              <Route path="*" element={<NotFoundPage />} />
            </Route>
          </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  )
}
