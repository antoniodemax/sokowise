import { useQuery } from '@tanstack/react-query'
import { Banknote, HandCoins, Receipt, ShoppingCart, TrendingUp, Wallet } from 'lucide-react'
import { useState, type ReactNode } from 'react'

import { Alert } from '@/components/ui/alert'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { EmptyState } from '@/components/ui/empty-state'
import { ErrorState } from '@/components/ui/error-state'
import { PageHeader } from '@/components/ui/page-header'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/features/auth/auth-context'
import { formatCalendarDate } from '@/lib/dates'
import { formatKsh } from '@/lib/money'
import { cn } from '@/lib/utils'

import { dashboardApi, type AnalyticsSummary, type DashboardPeriod } from './api'

const PERIODS: { value: DashboardPeriod; label: string }[] = [
  { value: 'today', label: 'Today' },
  { value: 'yesterday', label: 'Yesterday' },
  { value: 'this_week', label: 'This week' },
  { value: 'this_month', label: 'This month' },
]

function PeriodControl({ value, onChange }: { value: DashboardPeriod; onChange: (value: DashboardPeriod) => void }) {
  return (
    <div role="radiogroup" aria-label="Period" className="flex w-full gap-1 overflow-x-auto rounded-lg border border-border bg-card p-1 sm:w-auto">
      {PERIODS.map((period) => (
        <button
          key={period.value}
          type="button"
          role="radio"
          aria-checked={value === period.value}
          onClick={() => onChange(period.value)}
          className={cn(
            'min-h-9 flex-1 rounded-md px-3 text-sm font-medium whitespace-nowrap transition-colors sm:flex-none',
            value === period.value ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted hover:text-foreground',
          )}
        >
          {period.label}
        </button>
      ))}
    </div>
  )
}

interface MetricCardProps {
  label: string
  value: string
  icon: ReactNode
  hint?: string
  tone?: 'default' | 'positive' | 'negative'
}

/** The dashboard's metric pattern: label, one big figure, a one-line explanation. */
export function MetricCard({ label, value, icon, hint, tone = 'default' }: MetricCardProps) {
  return (
    <Card>
      <CardContent className="p-5">
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm font-medium text-muted-foreground">{label}</p>
          <span className="flex size-9 items-center justify-center rounded-lg bg-primary-soft text-primary [&_svg]:size-5" aria-hidden="true">
            {icon}
          </span>
        </div>
        <p className={cn('tabular mt-3 text-2xl font-semibold tracking-tight', tone === 'positive' && 'text-success', tone === 'negative' && 'text-destructive')}>{value}</p>
        {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
      </CardContent>
    </Card>
  )
}

function MetricSkeleton() {
  return (
    <Card>
      <CardContent className="space-y-3 p-5">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-8 w-32" />
        <Skeleton className="h-3 w-40" />
      </CardContent>
    </Card>
  )
}

function Metrics({ summary }: { summary: AnalyticsSummary }) {
  const net = summary.net_profit.startsWith('-') ? 'negative' : 'positive'
  const missing = summary.lines_missing_cost > 0
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
      <MetricCard label="Revenue" value={formatKsh(summary.revenue)} icon={<TrendingUp />} hint={`${summary.sales_count} ${summary.sales_count === 1 ? 'sale' : 'sales'} · includes credit sales`} />
      <MetricCard label="Cash collected" value={formatKsh(summary.cash_collected_total)} icon={<Banknote />} hint={`Cash ${formatKsh(summary.cash_collected.CASH ?? '0')} · M-Pesa ${formatKsh(summary.cash_collected.MPESA ?? '0')}`} />
      <MetricCard label="Owed by customers" value={formatKsh(summary.receivables_outstanding)} icon={<HandCoins />} hint="Outstanding credit right now" />
      <MetricCard label="Gross profit" value={formatKsh(summary.gross_profit)} icon={<Wallet />} hint={missing ? `${summary.lines_missing_cost} sale ${summary.lines_missing_cost === 1 ? 'line has' : 'lines have'} no cost price yet` : `After cost of goods ${formatKsh(summary.cogs)}`} />
      <MetricCard label="Expenses" value={formatKsh(summary.expenses)} icon={<Receipt />} hint="Money spent in this period" />
      <MetricCard label="Net profit" value={formatKsh(summary.net_profit)} icon={<ShoppingCart />} hint="Gross profit minus expenses" tone={net} />
    </div>
  )
}

export default function DashboardPage() {
  const { session } = useAuth()
  const [period, setPeriod] = useState<DashboardPeriod>('today')
  const isOwner = session?.role === 'OWNER'
  const query = useQuery({
    queryKey: ['analytics', 'summary', period],
    queryFn: ({ signal }) => dashboardApi.summary(period, signal),
    enabled: isOwner,
  })

  const summary = query.data
  const range = summary ? `${formatCalendarDate(summary.period.date_from)}${summary.period.date_from === summary.period.date_to ? '' : ` – ${formatCalendarDate(summary.period.date_to)}`}` : null

  return (
    <>
      <PageHeader
        title={`Hello, ${session?.user.full_name.split(' ')[0] ?? 'there'}`}
        description={isOwner ? (range ? `How ${session?.business.name} is doing · ${range}` : `How ${session?.business.name} is doing`) : `${session?.business.name}`}
        actions={isOwner ? <PeriodControl value={period} onChange={setPeriod} /> : undefined}
      />
      {!isOwner ? (
        <Card>
          <CardHeader>
            <CardTitle>Your day starts here</CardTitle>
            <CardDescription>Sales, products and customers are in the menu. Business figures are shown to the owner.</CardDescription>
          </CardHeader>
        </Card>
      ) : query.isPending ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3" aria-busy="true" aria-label="Loading figures">
          {Array.from({ length: 6 }, (_, i) => (
            <MetricSkeleton key={i} />
          ))}
        </div>
      ) : query.isError || !summary ? (
        <ErrorState error={query.error} title="Could not load your figures" onRetry={() => query.refetch()} />
      ) : summary.sales_count === 0 && summary.expenses === '0.00' && summary.receivables_outstanding === '0.00' ? (
        <EmptyState icon={ShoppingCart} title="Nothing recorded yet" description="Once you record sales and expenses, this dashboard shows your revenue, cash collected, profit and what customers owe." />
      ) : (
        <div className="space-y-4">
          {summary.products_missing_cost > 0 && (
            <Alert variant="warning" title="Profit is understated">
              {summary.products_missing_cost} {summary.products_missing_cost === 1 ? 'product has' : 'products have'} no cost price, so their sales count as pure profit. Add cost prices under Products to see the real margin.
            </Alert>
          )}
          <Metrics summary={summary} />
        </div>
      )}
    </>
  )
}
