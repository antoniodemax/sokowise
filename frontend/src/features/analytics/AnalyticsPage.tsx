import { useQuery } from '@tanstack/react-query'
import { BarChart3 } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'

import { Alert } from '@/components/ui/alert'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { EmptyState } from '@/components/ui/empty-state'
import { ErrorState } from '@/components/ui/error-state'
import { PageHeader } from '@/components/ui/page-header'
import { Select } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useAuth } from '@/features/auth/auth-context'
import { Metrics } from '@/features/dashboard/DashboardPage'
import { formatCalendarDate, formatDate, localDate } from '@/lib/dates'
import { formatKsh, formatQuantity } from '@/lib/money'

import { analyticsApi, type Granularity, type PeriodParams } from './api'
import { BarChart } from './BarChart'
import { PeriodPicker } from './PeriodPicker'

function bucketLabel(iso: string, granularity: Granularity, tz: string): string {
  const d = new Date(iso)
  if (granularity === 'month') return d.toLocaleDateString('en-KE', { month: 'short', year: '2-digit', timeZone: tz })
  return d.toLocaleDateString('en-KE', { day: 'numeric', month: 'short', timeZone: tz })
}

const SECTION_SKELETON = <div className="space-y-2" aria-busy="true"><Skeleton className="h-10" /><Skeleton className="h-10" /><Skeleton className="h-10" /></div>

export default function AnalyticsPage() {
  const { session } = useAuth()
  const tz = session?.business.timezone ?? 'Africa/Nairobi'
  const [period, setPeriod] = useState<PeriodParams>({ period: 'this_month' })
  const [granularity, setGranularity] = useState<Granularity>('day')
  const [productSort, setProductSort] = useState<'revenue' | 'quantity' | 'profit'>('revenue')
  const [slowDays, setSlowDays] = useState(30)
  const ready = period.period !== 'custom' || (!!period.date_from && !!period.date_to)
  const params: PeriodParams = period.period === 'custom' ? period : { period: period.period }

  const summary = useQuery({ queryKey: ['analytics', 'summary', params], queryFn: ({ signal }) => analyticsApi.summary(params, signal), enabled: ready })
  const series = useQuery({ queryKey: ['analytics', 'timeseries', params, granularity], queryFn: ({ signal }) => analyticsApi.timeseries({ ...params, granularity }, signal), enabled: ready })
  const products = useQuery({ queryKey: ['analytics', 'products', params, productSort], queryFn: ({ signal }) => analyticsApi.products({ ...params, sort: productSort, limit: 20 }, signal), enabled: ready })
  const categories = useQuery({ queryKey: ['analytics', 'categories', params], queryFn: ({ signal }) => analyticsApi.categories(params, signal), enabled: ready })
  const expenses = useQuery({ queryKey: ['analytics', 'expenses', params], queryFn: ({ signal }) => analyticsApi.expenses(params, signal), enabled: ready })
  const slow = useQuery({ queryKey: ['analytics', 'slow-products', slowDays], queryFn: ({ signal }) => analyticsApi.slowProducts(slowDays, signal) })

  const range = summary.data ? `${formatCalendarDate(summary.data.period.date_from)}${summary.data.period.date_from === summary.data.period.date_to ? '' : ` – ${formatCalendarDate(summary.data.period.date_to)}`}` : undefined

  return (
    <>
      <PageHeader title="Analytics" description={range ? `Figures for ${range}` : 'Revenue, profit and what sells.'} />
      <div className="mb-4"><PeriodPicker value={period} onChange={(v) => setPeriod(v.period === 'custom' && !v.date_from ? { period: 'custom', date_from: `${localDate(new Date(), tz).slice(0, 8)}01`, date_to: localDate(new Date(), tz) } : v)} /></div>
      {!ready ? (
        <p className="text-sm text-muted-foreground">Pick both dates to see the figures.</p>
      ) : summary.isPending ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3" aria-busy="true">{Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-28" />)}</div>
      ) : summary.isError ? (
        <ErrorState error={summary.error} title="Could not load the figures" onRetry={() => summary.refetch()} />
      ) : (
        <div className="space-y-6">
          {summary.data.products_missing_cost > 0 && (
            <Alert variant="warning" title="Profit is understated">
              {summary.data.products_missing_cost} {summary.data.products_missing_cost === 1 ? 'product has' : 'products have'} no cost price, so {summary.data.lines_missing_cost} sale {summary.data.lines_missing_cost === 1 ? 'line counts' : 'lines count'} as pure profit. <Link to="/products" className="font-medium underline">Add cost prices</Link> to see the real margin.
            </Alert>
          )}
          <Metrics summary={summary.data} />
          <div className="grid gap-4 text-sm sm:grid-cols-3">
            {(['CASH', 'MPESA', 'CREDIT'] as const).map((m) => (
              <Card key={m}><CardContent className="p-4"><p className="text-muted-foreground">{m === 'CASH' ? 'Sold for cash' : m === 'MPESA' ? 'Sold via M-Pesa' : 'Sold on credit'}</p><p className="tabular mt-1 text-lg font-semibold">{formatKsh(summary.data.tender_split[m] ?? '0')}</p>{m === 'CREDIT' && <p className="text-xs text-muted-foreground">Owed to you, not cash received</p>}</CardContent></Card>
            ))}
          </div>

          <Card>
            <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3">
              <div><CardTitle>Over time</CardTitle><CardDescription>Revenue, gross profit and expenses per {granularity}.</CardDescription></div>
              <div className="w-32"><Select aria-label="Granularity" value={granularity} onChange={(e) => setGranularity(e.target.value as Granularity)}><option value="day">By day</option><option value="week">By week</option><option value="month">By month</option></Select></div>
            </CardHeader>
            <CardContent>
              {series.isPending ? <Skeleton className="h-48" /> : series.isError ? <ErrorState error={series.error} title="Could not load the chart" onRetry={() => series.refetch()} /> : series.data.buckets.length === 0 ? <p className="text-sm text-muted-foreground">Nothing sold in this period.</p> : (
                <BarChart title={`Revenue, gross profit and expenses by ${granularity}`} series={[{ key: 'revenue', label: 'Revenue', color: 'var(--color-primary)' }, { key: 'gross_profit', label: 'Gross profit', color: 'var(--color-success)' }, { key: 'expenses', label: 'Expenses', color: 'var(--color-warning)' }]} rows={series.data.buckets.map((b) => ({ label: bucketLabel(b.bucket_start, series.data.granularity, tz), values: { revenue: b.revenue, gross_profit: b.gross_profit, expenses: b.expenses } }))} />
              )}
            </CardContent>
          </Card>

          <div className="grid gap-4 xl:grid-cols-2">
            <Card>
              <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3">
                <div><CardTitle>Products</CardTitle><CardDescription>What sold in this period.</CardDescription></div>
                <div className="w-40"><Select aria-label="Sort products" value={productSort} onChange={(e) => setProductSort(e.target.value as typeof productSort)}><option value="revenue">By revenue</option><option value="quantity">By quantity</option><option value="profit">By profit</option></Select></div>
              </CardHeader>
              <CardContent>
                {products.isPending ? SECTION_SKELETON : products.isError ? <ErrorState error={products.error} title="Could not load products" onRetry={() => products.refetch()} /> : products.data.length === 0 ? <p className="text-sm text-muted-foreground">No sales in this period.</p> : (
                  <Table>
                    <TableHeader><TableRow><TableHead>Product</TableHead><TableHead className="text-right">Qty</TableHead><TableHead className="text-right">Revenue</TableHead><TableHead className="text-right">Gross profit</TableHead></TableRow></TableHeader>
                    <TableBody>
                      {products.data.map((p) => (
                        <TableRow key={p.product_id}>
                          <TableCell><Link to={`/products/${p.product_id}`} className="font-medium hover:underline">{p.name}</Link>{!p.is_active && <span className="ml-1 text-xs text-muted-foreground">(archived)</span>}{p.lines_missing_cost > 0 && <span className="block text-xs text-warning">cost missing on {p.lines_missing_cost} {p.lines_missing_cost === 1 ? 'line' : 'lines'}</span>}</TableCell>
                          <TableCell className="tabular text-right">{formatQuantity(p.quantity)}</TableCell>
                          <TableCell className="tabular text-right">{formatKsh(p.revenue)}</TableCell>
                          <TableCell className="tabular text-right">{formatKsh(p.gross_profit)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle>Categories</CardTitle><CardDescription>Revenue and gross profit by category.</CardDescription></CardHeader>
              <CardContent>
                {categories.isPending ? SECTION_SKELETON : categories.isError ? <ErrorState error={categories.error} title="Could not load categories" onRetry={() => categories.refetch()} /> : categories.data.length === 0 ? <p className="text-sm text-muted-foreground">No sales in this period.</p> : (
                  <Table>
                    <TableHeader><TableRow><TableHead>Category</TableHead><TableHead className="text-right">Qty</TableHead><TableHead className="text-right">Revenue</TableHead><TableHead className="text-right">Gross profit</TableHead></TableRow></TableHeader>
                    <TableBody>
                      {categories.data.map((c) => (
                        <TableRow key={c.category_id ?? 'none'}>
                          <TableCell className="font-medium">{c.name ?? <span className="text-muted-foreground">Uncategorised</span>}{c.lines_missing_cost > 0 && <span className="block text-xs text-warning">cost missing on {c.lines_missing_cost} {c.lines_missing_cost === 1 ? 'line' : 'lines'}</span>}</TableCell>
                          <TableCell className="tabular text-right">{formatQuantity(c.quantity)}</TableCell>
                          <TableCell className="tabular text-right">{formatKsh(c.revenue)}</TableCell>
                          <TableCell className="tabular text-right">{formatKsh(c.gross_profit)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle>Expenses</CardTitle><CardDescription>Where the money went.</CardDescription></CardHeader>
              <CardContent>
                {expenses.isPending ? SECTION_SKELETON : expenses.isError ? <ErrorState error={expenses.error} title="Could not load expenses" onRetry={() => expenses.refetch()} /> : expenses.data.count === 0 ? <p className="text-sm text-muted-foreground">No expenses in this period.</p> : (
                  <>
                    <p className="mb-3 text-sm text-muted-foreground">{expenses.data.count} {expenses.data.count === 1 ? 'expense' : 'expenses'} · cash {formatKsh(expenses.data.by_method.CASH ?? '0')} · M-Pesa {formatKsh(expenses.data.by_method.MPESA ?? '0')}</p>
                    <Table>
                      <TableHeader><TableRow><TableHead>Category</TableHead><TableHead className="text-right">Count</TableHead><TableHead className="text-right">Total</TableHead></TableRow></TableHeader>
                      <TableBody>
                        {expenses.data.by_category.map((c) => <TableRow key={c.key}><TableCell className="font-medium">{c.key}</TableCell><TableCell className="tabular text-right">{c.count}</TableCell><TableCell className="tabular text-right">{formatKsh(c.total)}</TableCell></TableRow>)}
                        <TableRow><TableCell className="font-semibold">Total</TableCell><TableCell /><TableCell className="tabular text-right font-semibold">{formatKsh(expenses.data.total)}</TableCell></TableRow>
                      </TableBody>
                    </Table>
                  </>
                )}
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3">
                <div><CardTitle>Not selling</CardTitle><CardDescription>Stocked products with no sale recently.</CardDescription></div>
                <div className="w-36"><Select aria-label="Days without a sale" value={slowDays} onChange={(e) => setSlowDays(Number(e.target.value))}><option value={14}>14 days</option><option value={30}>30 days</option><option value={60}>60 days</option><option value={90}>90 days</option></Select></div>
              </CardHeader>
              <CardContent>
                {slow.isPending ? SECTION_SKELETON : slow.isError ? <ErrorState error={slow.error} title="Could not load slow products" onRetry={() => slow.refetch()} /> : slow.data.length === 0 ? <EmptyState icon={BarChart3} title="Everything is moving" description={`Every stocked product sold in the last ${slowDays} days.`} /> : (
                  <Table>
                    <TableHeader><TableRow><TableHead>Product</TableHead><TableHead className="text-right">In stock</TableHead><TableHead className="text-right">Last sold</TableHead></TableRow></TableHeader>
                    <TableBody>
                      {slow.data.map((p) => <TableRow key={p.product_id}><TableCell><Link to={`/products/${p.product_id}`} className="font-medium hover:underline">{p.name}</Link></TableCell><TableCell className="tabular text-right">{formatQuantity(p.stock_quantity)}</TableCell><TableCell className="text-right text-muted-foreground">{p.last_sold_at ? formatDate(p.last_sold_at, tz) : 'Never'}</TableCell></TableRow>)}
                    </TableBody>
                  </Table>
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      )}
    </>
  )
}
