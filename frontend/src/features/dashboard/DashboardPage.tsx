import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, Banknote, HandCoins, Package, Plus, ShoppingCart, Smartphone, Sparkles, TrendingUp, UserRound } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { Link } from 'react-router'

import { Alert } from '@/components/ui/alert'
import { buttonVariants } from '@/components/ui/button-variants'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { EmptyState } from '@/components/ui/empty-state'
import { ErrorState } from '@/components/ui/error-state'
import { PageHeader } from '@/components/ui/page-header'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/features/auth/auth-context'
import { useDebtors } from '@/features/customers/hooks'
import { useLowStock } from '@/features/inventory/hooks'
import { useMpesaReconciliation } from '@/features/mpesa/hooks'
import { useProducts } from '@/features/products/hooks'
import { formatCalendarDate, localDate } from '@/lib/dates'
import { formatKsh, formatQuantity } from '@/lib/money'
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
    <div role="radiogroup" aria-label="Period" className="grid w-full grid-cols-4 gap-1 rounded-lg border border-border bg-card p-1 sm:flex sm:w-auto">
      {PERIODS.map((period) => (
        <button
          key={period.value}
          type="button"
          role="radio"
          aria-checked={value === period.value}
          onClick={() => onChange(period.value)}
          className={cn(
            'min-h-10 rounded-md px-2 text-[13px] font-medium whitespace-nowrap transition-colors sm:min-h-9 sm:px-3 sm:text-sm',
            value === period.value ? 'bg-primary text-primary-foreground shadow-xs' : 'text-muted-foreground hover:bg-muted hover:text-foreground',
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
  /** The one figure to read first: a tinted card. */
  emphasis?: boolean
  className?: string
}

/** The dashboard's metric pattern: label, one big figure, a one-line explanation. */
export function MetricCard({ label, value, icon, hint, tone = 'default', emphasis, className }: MetricCardProps) {
  return (
    <Card className={cn(emphasis && 'border-primary/30 bg-primary-soft/40', className)}>
      <CardContent className="p-4 sm:p-5">
        <div className="flex items-center justify-between gap-3">
          <p className="line-clamp-2 text-[13px] leading-tight font-medium text-muted-foreground sm:text-sm">{label}</p>
          <span className={cn('flex size-8 shrink-0 items-center justify-center rounded-lg [&_svg]:size-4', emphasis ? 'bg-primary text-primary-foreground' : 'bg-primary-soft text-primary')} aria-hidden="true">
            {icon}
          </span>
        </div>
        <p className={cn('tabular mt-2 text-xl font-semibold tracking-tight sm:mt-3 sm:text-2xl', tone === 'positive' && 'text-success', tone === 'negative' && 'text-destructive')}>{value}</p>
        {hint && <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{hint}</p>}
      </CardContent>
    </Card>
  )
}

/** Profit before costs − costs = profit, read as one line instead of three unrelated boxes. */
function ProfitCard({ summary, className }: { summary: AnalyticsSummary; className?: string }) {
  const negative = summary.net_profit.startsWith('-')
  const missing = summary.lines_missing_cost > 0
  const cell = (glyph: string | null, label: string, value: string, hint: string, tone?: 'negative' | 'positive') => (
    <div className="flex min-w-0 items-center justify-between gap-3 sm:block">
      <div className="min-w-0">
        <p className="text-[13px] font-medium text-muted-foreground sm:text-sm">
          {glyph && <span className="mr-1.5 sm:hidden" aria-hidden="true">{glyph}</span>}
          {label}
        </p>
        <p className="line-clamp-2 text-xs text-muted-foreground sm:hidden">{hint}</p>
      </div>
      <p className={cn('tabular shrink-0 text-lg font-semibold tracking-tight sm:mt-1 sm:text-2xl', tone === 'negative' && 'text-destructive', tone === 'positive' && 'text-success')}>{value}</p>
      <p className="mt-0.5 hidden line-clamp-2 text-xs text-muted-foreground sm:block">{hint}</p>
    </div>
  )
  const op = (glyph: string) => <span className="hidden self-center pb-4 text-lg text-muted-foreground/70 sm:block" aria-hidden="true">{glyph}</span>
  return (
    <Card className={className}>
      <CardContent className="grid gap-3 divide-y divide-border p-4 sm:grid-cols-[1fr_auto_1fr_auto_1fr] sm:items-start sm:gap-4 sm:divide-y-0 sm:p-5 [&>div+div]:pt-3 sm:[&>div+div]:pt-0">
        {cell(null, 'Profit before costs', formatKsh(summary.gross_profit), missing ? `${summary.lines_missing_cost} sale ${summary.lines_missing_cost === 1 ? 'line has' : 'lines have'} no cost price yet` : `Goods cost you ${formatKsh(summary.cogs)}`)}
        {op('−')}
        {cell('−', 'Matumizi (costs)', formatKsh(summary.expenses), 'Money spent in this period')}
        {op('=')}
        {cell('=', 'Profit', formatKsh(summary.net_profit), 'After your costs', negative ? 'negative' : 'positive')}
      </CardContent>
    </Card>
  )
}


function MetricSkeleton({ className }: { className?: string }) {
  return (
    <Card className={className}>
      <CardContent className="space-y-3 p-4 sm:p-5">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-8 w-32" />
        <Skeleton className="h-3 w-40" />
      </CardContent>
    </Card>
  )
}

export function Metrics({ summary }: { summary: AnalyticsSummary }) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-3">
      <MetricCard emphasis className="col-span-2 lg:col-span-1" label="Sold" value={formatKsh(summary.revenue)} icon={<TrendingUp />} hint={`${summary.sales_count} ${summary.sales_count === 1 ? 'sale' : 'sales'} · includes deni sales`} />
      <MetricCard label="In your pocket" value={formatKsh(summary.cash_collected_total)} icon={<Banknote />} hint={`Cash ${formatKsh(summary.cash_collected.CASH ?? '0')} · M-Pesa ${formatKsh(summary.cash_collected.MPESA ?? '0')}`} />
      <MetricCard label="Deni (owed to you)" value={formatKsh(summary.receivables_outstanding)} icon={<HandCoins />} hint="Customers still to pay" />
      <ProfitCard summary={summary} className="col-span-2 lg:col-span-3" />
    </div>
  )
}

function QuickActions() {
  return (
    <div className="grid grid-cols-3 gap-2 sm:flex sm:flex-wrap" aria-label="Quick actions">
      <Link to="/sales/new" className={cn(buttonVariants(), 'px-2 sm:px-4')}><ShoppingCart aria-hidden="true" /> New sale</Link>
      <Link to="/products" className={cn(buttonVariants({ variant: 'outline' }), 'px-2 sm:px-4')}><Package aria-hidden="true" /> Products</Link>
      <Link to="/customers" className={cn(buttonVariants({ variant: 'outline' }), 'px-2 sm:px-4')}><UserRound aria-hidden="true" /> Customers</Link>
    </div>
  )
}

function LowStockCard() {
  const lowStock = useLowStock()
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><AlertTriangle className="size-4 text-warning" aria-hidden="true" /> Running low</CardTitle>
        <CardDescription>Products at or below their low-stock alert.</CardDescription>
      </CardHeader>
      <CardContent>
        {lowStock.isPending ? (
          <div className="space-y-2" aria-busy="true"><Skeleton className="h-5" /><Skeleton className="h-5" /></div>
        ) : lowStock.isError ? (
          <ErrorState error={lowStock.error} title="Could not check stock" onRetry={() => lowStock.refetch()} />
        ) : lowStock.data.length === 0 ? (
          <p className="text-sm text-muted-foreground">Nothing is running low.</p>
        ) : (
          <ul className="divide-y divide-border text-sm">
            {lowStock.data.slice(0, 6).map((p) => (
              <li key={p.product_id}>
                <Link to={`/products/${p.product_id}`} className="-mx-2 flex min-h-11 items-center justify-between gap-3 rounded-md px-2 py-2 transition-colors hover:bg-muted">
                  <span className="min-w-0 truncate font-medium">{p.name}</span>
                  <span className="tabular shrink-0 rounded-full bg-warning-soft px-2 py-0.5 text-xs font-medium text-warning">{formatQuantity(p.stock_quantity)} {p.unit} left</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
        {lowStock.data && lowStock.data.length > 6 && <Link to="/inventory" className="mt-1 inline-flex min-h-11 items-center text-sm font-medium text-primary hover:underline">See all {lowStock.data.length}</Link>}
      </CardContent>
    </Card>
  )
}

/** Shown to the owner until the shop has at least one product. */
function SetupCard() {
  const products = useProducts({ limit: 1 })
  if (products.isPending || products.isError || products.data.length > 0) return null
  return (
    <Card className="mb-4 border-primary/40 bg-primary-soft/30">
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Sparkles className="size-4 text-primary" aria-hidden="true" /> Start here: what do you sell?</CardTitle>
        <CardDescription>Tick your items from a ready-made list for your kind of shop. Two minutes, then you can sell.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-wrap gap-2">
        <Link to="/setup" className={buttonVariants({ size: 'lg' })}>Choose my items</Link>
        <Link to="/products" className={buttonVariants({ variant: 'outline', size: 'lg' })}>Add one by one</Link>
      </CardContent>
    </Card>
  )
}

function MpesaCard({ timeZone }: { timeZone: string }) {
  const today = localDate(new Date(), timeZone)
  const summary = useMpesaReconciliation(today)
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Smartphone className="size-4 text-primary" aria-hidden="true" /> M-Pesa today</CardTitle>
        <CardDescription>Messages you added, and whether each is recorded.</CardDescription>
      </CardHeader>
      <CardContent>
        {summary.isPending ? (
          <div className="space-y-2" aria-busy="true"><Skeleton className="h-5" /><Skeleton className="h-5" /></div>
        ) : summary.isError ? (
          <ErrorState error={summary.error} title="Could not load M-Pesa" onRetry={() => summary.refetch()} />
        ) : (
          <dl className="grid grid-cols-3 gap-3 text-sm">
            <div className="rounded-lg bg-muted/60 px-3 py-2"><dt className="text-xs text-muted-foreground">Received</dt><dd className="tabular mt-0.5 font-semibold">{formatKsh(summary.data.received_total)}</dd></div>
            <div className="rounded-lg bg-muted/60 px-3 py-2"><dt className="text-xs text-muted-foreground">Recorded</dt><dd className="tabular mt-0.5 font-semibold">{formatKsh(summary.data.matched_total)}</dd></div>
            <div className={cn('rounded-lg px-3 py-2', summary.data.unmatched_count > 0 ? 'bg-warning-soft' : 'bg-muted/60')}><dt className="text-xs text-muted-foreground">Not recorded</dt><dd className={cn('tabular mt-0.5 font-semibold', summary.data.unmatched_count > 0 && 'text-warning')}>{summary.data.unmatched_count}</dd></div>
          </dl>
        )}
        <Link to="/mpesa" className="mt-1 inline-flex min-h-11 items-center text-sm font-medium text-primary hover:underline">Add or check messages</Link>
      </CardContent>
    </Card>
  )
}


function DebtorsCard() {
  const debtors = useDebtors('balance')
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><HandCoins className="size-4 text-warning" aria-hidden="true" /> Who owes you most</CardTitle>
        <CardDescription>Outstanding credit, largest first.</CardDescription>
      </CardHeader>
      <CardContent>
        {debtors.isPending ? (
          <div className="space-y-2" aria-busy="true"><Skeleton className="h-5" /><Skeleton className="h-5" /></div>
        ) : debtors.isError ? (
          <ErrorState error={debtors.error} title="Could not load debtors" onRetry={() => debtors.refetch()} />
        ) : debtors.data.length === 0 ? (
          <p className="text-sm text-muted-foreground">Nobody owes you money.</p>
        ) : (
          <ul className="divide-y divide-border text-sm">
            {debtors.data.slice(0, 5).map((d) => (
              <li key={d.customer_id}>
                <Link to={`/customers/${d.customer_id}`} className="-mx-2 flex min-h-11 items-center justify-between gap-3 rounded-md px-2 py-2 transition-colors hover:bg-muted">
                  <span className="min-w-0 truncate font-medium">{d.name}</span>
                  <span className="tabular shrink-0 font-semibold text-warning">{formatKsh(d.balance)}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
        {debtors.data && debtors.data.length > 5 && <Link to="/customers?view=debtors" className="mt-1 inline-flex min-h-11 items-center text-sm font-medium text-primary hover:underline">See all {debtors.data.length}</Link>}
      </CardContent>
    </Card>
  )
}

export default function DashboardPage() {
  const { session } = useAuth()
  const [period, setPeriod] = useState<DashboardPeriod>('today')
  const isOwner = session?.role === 'OWNER'
  const tz = session?.business.timezone ?? 'Africa/Nairobi'
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
      {isOwner && <SetupCard />}
      <div className="mb-4"><QuickActions /></div>
      {!isOwner ? (
        <div className="grid gap-4 md:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>Your day starts here</CardTitle>
              <CardDescription>Record sales, add customers and check stock from the menu. Business figures are shown to the owner.</CardDescription>
            </CardHeader>
            <CardContent><Link to="/sales/new" className={buttonVariants({ size: 'lg' })}><Plus aria-hidden="true" /> Record a sale</Link></CardContent>
          </Card>
          <LowStockCard />
          <MpesaCard timeZone={tz} />
        </div>
      ) : query.isPending ? (
        <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-3" aria-busy="true" aria-label="Loading figures">
          <MetricSkeleton className="col-span-2 lg:col-span-1" />
          <MetricSkeleton />
          <MetricSkeleton />
          <MetricSkeleton className="col-span-2 lg:col-span-3" />
        </div>
      ) : query.isError || !summary ? (
        <ErrorState error={query.error} title="Could not load your figures" onRetry={() => query.refetch()} />
      ) : summary.sales_count === 0 && summary.expenses === '0.00' && summary.receivables_outstanding === '0.00' ? (
        <div className="space-y-4">
          <EmptyState icon={ShoppingCart} title="Nothing recorded yet" description="Once you record sales and expenses, this dashboard shows your revenue, cash collected, profit and what customers owe." />
          <div className="grid gap-4 md:grid-cols-2"><LowStockCard /><DebtorsCard /><div className="md:col-span-2"><MpesaCard timeZone={tz} /></div></div>
        </div>
      ) : (
        <div className="space-y-4">
          {summary.products_missing_cost > 0 && (
            <Alert variant="warning" title="Profit is understated">
              {summary.products_missing_cost} {summary.products_missing_cost === 1 ? 'product has no cost price, so its' : 'products have no cost price, so their'} sales count as pure profit. Add cost prices under Products to see the real margin.
            </Alert>
          )}
          <Metrics summary={summary} />
          <div className="grid gap-4 md:grid-cols-2"><LowStockCard /><DebtorsCard /><div className="md:col-span-2"><MpesaCard timeZone={tz} /></div></div>
        </div>
      )}
    </>
  )
}
