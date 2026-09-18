import { useQuery } from '@tanstack/react-query'
import { Activity, Building2, MessageSquare, RefreshCw, ShoppingCart, Trash2, Users, Wallet } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { ErrorState } from '@/components/ui/error-state'
import { PageHeader } from '@/components/ui/page-header'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { BUSINESS_TYPES } from '@/features/auth/api'
import { MetricCard } from '@/features/dashboard/DashboardPage'
import { formatDate, formatDateTime, formatDayMonth } from '@/lib/dates'
import { formatKsh } from '@/lib/money'
import { queryKeys } from '@/lib/query-keys'
import { cn } from '@/lib/utils'

import { adminApi, type PlatformBusinessRow, type PlatformOverview } from './api'
import { DeleteBusinessDialog } from './DeleteBusinessDialog'

const TYPE_LABEL: Record<string, string> = Object.fromEntries(BUSINESS_TYPES.map((t) => [t.value, t.label]))

/** "20 Aug" from a calendar date; the year is in the card title's context. */
function dayMonth(ymd: string): string {
  const [year, month, day] = ymd.split('-').map(Number)
  if (!year || !month || !day) return ymd
  return new Intl.DateTimeFormat('en-KE', { day: 'numeric', month: 'short', timeZone: 'UTC' }).format(new Date(Date.UTC(year, month - 1, day)))
}

/** "today", "yesterday", "3 days ago", else the date — for last-activity columns. */
function relative(iso: string | null, tz: string, now: Date, empty = 'never'): string {
  if (!iso) return empty
  const days = Math.floor((now.getTime() - new Date(iso).getTime()) / 86_400_000)
  if (days <= 0) return 'today'
  if (days === 1) return 'yesterday'
  if (days < 14) return `${days} days ago`
  return formatDayMonth(iso, tz)
}

/**
 * The operator's view of the whole platform: how many businesses and people have signed up,
 * how many are active, and what they record. Counts and totals only; nothing here names a
 * customer or shows a tester's phone number.
 */
export default function AdminPage() {
  const query = useQuery({ queryKey: queryKeys.admin.overview, queryFn: ({ signal }) => adminApi.overview(signal) })

  return (
    <>
      <PageHeader
        title="Admin"
        description="How the pilot is going across every business. Counts only; nobody's records are shown here."
        actions={
          <Button variant="outline" onClick={() => query.refetch()} loading={query.isFetching && !query.isPending}>
            <RefreshCw aria-hidden="true" /> Refresh
          </Button>
        }
      />
      {query.isPending ? (
        <div className="space-y-4" aria-busy="true" aria-label="Loading platform figures">
          <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4"><Skeleton className="h-28" /><Skeleton className="h-28" /><Skeleton className="h-28" /><Skeleton className="h-28" /></div>
          <Skeleton className="h-40" />
          <Skeleton className="h-64" />
        </div>
      ) : query.isError ? (
        <ErrorState error={query.error} title="Could not load the platform figures" onRetry={() => query.refetch()} />
      ) : (
        <Overview data={query.data} />
      )}
    </>
  )
}

function Overview({ data }: { data: PlatformOverview }) {
  const { totals, last_7_days: week, last_30_days: month, timezone: tz } = data
  const [deleting, setDeleting] = useState<PlatformBusinessRow | null>(null)
  const now = new Date(data.generated_at)
  const signups30 = data.signups_by_day.reduce((sum, d) => sum + d.businesses, 0)
  const maxSignups = Math.max(1, ...data.signups_by_day.map((d) => d.businesses))
  const activeShare = totals.businesses ? Math.round((week.businesses_with_sales / totals.businesses) * 100) : 0

  return (
    <div className="space-y-4 sm:space-y-6">
      {/* Who is here */}
      <section aria-label="Totals" className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
        <MetricCard emphasis label="Businesses" value={String(totals.businesses)} icon={<Building2 />} hint={`${totals.businesses_active} active · ${week.new_businesses} new this week`} />
        <MetricCard label="People" value={String(totals.users)} icon={<Users />} hint={`${totals.owners} owners · ${totals.staff} staff · ${week.users_signed_in} signed in this week`} />
        <MetricCard label="Active this week" value={String(week.businesses_with_sales)} icon={<Activity />} hint={totals.businesses ? `${activeShare}% of businesses recorded a sale in 7 days` : 'businesses with a sale in 7 days'} />
        <MetricCard label="Copilot questions" value={String(totals.copilot_messages)} icon={<MessageSquare />} hint={`${totals.proposals_applied} proposals confirmed`} />
      </section>

      {/* What they record */}
      <Card>
        <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle>What businesses are recording</CardTitle>
            <CardDescription>Across every business, all time and recently.</CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-4 text-sm sm:grid-cols-3 lg:grid-cols-6">
            <Figure icon={<ShoppingCart />} label="Sales recorded" value={String(totals.sales)} hint={`${week.sales} this week · ${month.sales} this month`} />
            <Figure icon={<Wallet />} label="Money recorded" value={formatKsh(totals.revenue)} hint={`${formatKsh(week.revenue)} this week`} />
            <Figure label="Deni outstanding" value={formatKsh(totals.credit_outstanding)} hint="owed by customers right now" />
            <Figure label="Products" value={String(totals.products)} hint={`${totals.customers} customers`} />
            <Figure label="Expenses" value={String(totals.expenses)} hint="entries recorded" />
            <Figure label="M-Pesa & receipts" value={`${totals.mpesa_messages} · ${totals.receipts}`} hint="messages · receipt photos" />
          </dl>
        </CardContent>
      </Card>

      {/* Sign-ups */}
      <Card>
        <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle>New businesses, last 30 days</CardTitle>
            <CardDescription>Sign-ups per day in {tz}.</CardDescription>
          </div>
          <p className="text-sm text-muted-foreground"><span className="tabular font-semibold text-foreground">{signups30}</span> in 30 days</p>
        </CardHeader>
        <CardContent>
          <figure>
            <div className="flex h-28 items-end gap-0.5 sm:gap-1" aria-hidden="true">
              {data.signups_by_day.map((d) => (
                <div key={d.day} className="group relative flex h-full flex-1 items-end" title={`${dayMonth(d.day)}: ${d.businesses}`}>
                  <div className={cn('w-full rounded-t-sm transition-colors', d.businesses ? 'bg-primary group-hover:bg-primary-hover' : 'bg-muted')} style={{ height: d.businesses ? `${Math.max(8, (d.businesses / maxSignups) * 100)}%` : '3px' }} />
                </div>
              ))}
            </div>
            <div className="mt-1 flex justify-between text-[11px] text-muted-foreground" aria-hidden="true">
              <span>{dayMonth(data.signups_by_day[0]?.day ?? '')}</span>
              <span>{dayMonth(data.signups_by_day[Math.floor(data.signups_by_day.length / 2)]?.day ?? '')}</span>
              <span>{dayMonth(data.signups_by_day[data.signups_by_day.length - 1]?.day ?? '')}</span>
            </div>
            <figcaption className="sr-only">Sign-ups per day</figcaption>
            <ol className="sr-only" aria-label="Sign-ups per day">
              {data.signups_by_day.map((d) => <li key={d.day}>{dayMonth(d.day)}: {d.businesses}</li>)}
            </ol>
          </figure>
        </CardContent>
      </Card>

      {/* Businesses */}
      <Card>
        <CardHeader>
          <CardTitle>Businesses</CardTitle>
          <CardDescription>Newest first. Names and counts only.</CardDescription>
        </CardHeader>
        <CardContent className="p-0 sm:p-6 sm:pt-0">
          {/* Phones: one card per business */}
          <ul className="divide-y divide-border sm:hidden" aria-label="Businesses">
            {data.businesses.map((b) => (
              <li key={b.id} className="space-y-1.5 px-5 py-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate font-medium">{b.name}</p>
                    <p className="text-xs text-muted-foreground">{TYPE_LABEL[b.business_type] ?? b.business_type} · joined {formatDate(b.created_at, tz)}</p>
                  </div>
                  <StatusBadge business={b} />
                </div>
                <dl className="grid grid-cols-3 gap-2 text-xs">
                  <div><dt className="text-muted-foreground">Products</dt><dd className="tabular font-medium">{b.products}</dd></div>
                  <div><dt className="text-muted-foreground">Sales</dt><dd className="tabular font-medium">{b.sales}</dd></div>
                  <div><dt className="text-muted-foreground">Last sale</dt><dd className="font-medium">{relative(b.last_sale_at, tz, now)}</dd></div>
                </dl>
                <Button variant="ghost" size="sm" className="-ml-2 text-muted-foreground hover:bg-destructive-soft hover:text-destructive" aria-label={`Delete ${b.name}`} onClick={() => setDeleting(b)}>
                  <Trash2 aria-hidden="true" /> Delete
                </Button>
              </li>
            ))}
          </ul>
          {/* Larger screens: the table */}
          <div className="hidden sm:block">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Business</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Joined</TableHead>
                  <TableHead className="text-right">Products</TableHead>
                  <TableHead className="text-right">Sales</TableHead>
                  <TableHead>Last sale</TableHead>
                  <TableHead>Last sign-in</TableHead>
                  <TableHead className="text-right"><span className="sr-only">Actions</span></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.businesses.map((b) => (
                  <TableRow key={b.id}>
                    <TableCell className="font-medium">
                      <span className="flex items-center gap-2">{b.name}<StatusBadge business={b} /></span>
                    </TableCell>
                    <TableCell className="text-muted-foreground">{TYPE_LABEL[b.business_type] ?? b.business_type}</TableCell>
                    <TableCell className="text-muted-foreground">{formatDate(b.created_at, tz)}</TableCell>
                    <TableCell className="tabular text-right">{b.products}</TableCell>
                    <TableCell className="tabular text-right">{b.sales}</TableCell>
                    <TableCell title={b.last_sale_at ? formatDateTime(b.last_sale_at, tz) : undefined}>{relative(b.last_sale_at, tz, now)}</TableCell>
                    <TableCell title={b.last_login_at ? formatDateTime(b.last_login_at, tz) : undefined}>{relative(b.last_login_at, tz, now, 'not since sign-up')}</TableCell>
                    <TableCell className="text-right">
                      <Button variant="ghost" size="icon" className="size-9 text-muted-foreground hover:bg-destructive-soft hover:text-destructive" aria-label={`Delete ${b.name}`} onClick={() => setDeleting(b)}>
                        <Trash2 aria-hidden="true" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      <p className="text-xs text-muted-foreground">
        Figures at {formatDateTime(data.generated_at, tz)} · <Link to="/dashboard" className="text-primary hover:underline">Back to your own dashboard</Link>
      </p>
      <DeleteBusinessDialog business={deleting} onOpenChange={(open) => !open && setDeleting(null)} />
    </div>
  )
}

function Figure({ icon, label, value, hint }: { icon?: React.ReactNode; label: string; value: string; hint: string }) {
  return (
    <div className="min-w-0">
      <dt className="flex items-center gap-1.5 text-xs text-muted-foreground [&_svg]:size-3.5">{icon}{label}</dt>
      <dd className="tabular mt-0.5 text-lg font-semibold tracking-tight">{value}</dd>
      <dd className="text-xs text-muted-foreground">{hint}</dd>
    </div>
  )
}

/** Inactive, quiet (no sale yet), or nothing: only what helps the operator decide who to call. */
function StatusBadge({ business }: { business: PlatformBusinessRow }) {
  if (!business.is_active) return <Badge variant="neutral" className="shrink-0 whitespace-nowrap">inactive</Badge>
  if (business.sales === 0) return <Badge variant="warning" className="shrink-0 whitespace-nowrap">no sales yet</Badge>
  return null
}
