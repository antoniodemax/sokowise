import { lazy, Suspense } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router'

import { Spinner } from '@/components/ui/spinner'

import { RedirectIfAuthenticated, RequireAuth, RequireOwner, RequirePlatformAdmin } from './guards'
import { AppShell } from './layouts/AppShell'
import { AuthLayout } from './layouts/AuthLayout'

const LoginPage = lazy(() => import('@/features/auth/LoginPage'))
const RegisterPage = lazy(() => import('@/features/auth/RegisterPage'))
const ChangePasswordPage = lazy(() => import('@/features/auth/ChangePasswordPage'))
const ForgotPasswordPage = lazy(() => import('@/features/auth/ForgotPasswordPage'))
const GoogleRegisterPage = lazy(() => import('@/features/auth/GoogleRegisterPage'))
const HomePage = lazy(() => import('@/features/marketing/HomePage'))
const DashboardPage = lazy(() => import('@/features/dashboard/DashboardPage'))
const SalesPage = lazy(() => import('@/features/sales/SalesPage'))
const SellPage = lazy(() => import('@/features/sales/SellPage'))
const MpesaPage = lazy(() => import('@/features/mpesa/MpesaPage'))
const SetupPage = lazy(() => import('@/features/products/SetupPage'))
const SaleDetailPage = lazy(() => import('@/features/sales/SaleDetailPage'))
const ProductsPage = lazy(() => import('@/features/products/ProductsPage'))
const ProductDetailPage = lazy(() => import('@/features/products/ProductDetailPage'))
const InventoryPage = lazy(() => import('@/features/inventory/InventoryPage'))
const ReceiptsPage = lazy(() => import('@/features/receipts/ReceiptsPage'))
const ReceiptReviewPage = lazy(() => import('@/features/receipts/ReceiptReviewPage'))
const CustomersPage = lazy(() => import('@/features/customers/CustomersPage'))
const CustomerDetailPage = lazy(() => import('@/features/customers/CustomerDetailPage'))
const ExpensesPage = lazy(() => import('@/features/expenses/ExpensesPage'))
const AnalyticsPage = lazy(() => import('@/features/analytics/AnalyticsPage'))
const AssistantPage = lazy(() => import('@/features/assistant/AssistantPage'))
const SettingsPage = lazy(() => import('@/features/settings/SettingsPage'))
const AdminPage = lazy(() => import('@/features/admin/AdminPage'))
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
          {/* The public site: no session needed, no guard. */}
          <Route path="/" element={<HomePage />} />
          <Route element={<RedirectIfAuthenticated />}>
            <Route element={<AuthLayout />}>
              <Route path="/login" element={<LoginPage />} />
              <Route path="/register" element={<RegisterPage />} />
              <Route path="/register/google" element={<GoogleRegisterPage />} />
              <Route path="/forgot-password" element={<ForgotPasswordPage />} />
            </Route>
          </Route>
          <Route element={<RequireAuth />}>
            <Route element={<AuthLayout />}>
              <Route path="/change-password" element={<ChangePasswordPage />} />
            </Route>
            <Route element={<AppShell />}>
              <Route path="/dashboard" element={<DashboardPage />} />
              <Route path="/sales" element={<SalesPage />} />
              <Route path="/sales/new" element={<SellPage />} />
              <Route path="/sales/:saleId" element={<SaleDetailPage />} />
              <Route path="/mpesa" element={<MpesaPage />} />
              <Route path="/products" element={<ProductsPage />} />
              <Route path="/products/:productId" element={<ProductDetailPage />} />
              <Route path="/inventory" element={<InventoryPage />} />
              <Route path="/customers" element={<CustomersPage />} />
              <Route path="/customers/:customerId" element={<CustomerDetailPage />} />
              <Route element={<RequireOwner />}>
                <Route path="/setup" element={<SetupPage />} />
                <Route path="/inventory/receipts" element={<ReceiptsPage />} />
                <Route path="/inventory/receipts/:receiptId" element={<ReceiptReviewPage />} />
                <Route path="/expenses" element={<ExpensesPage />} />
                <Route path="/analytics" element={<AnalyticsPage />} />
                <Route path="/assistant" element={<AssistantPage />} />
              </Route>
              <Route path="/settings" element={<SettingsPage />} />
              <Route element={<RequirePlatformAdmin />}>
                <Route path="/admin" element={<AdminPage />} />
              </Route>
              <Route path="*" element={<NotFoundPage />} />
            </Route>
          </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  )
}
