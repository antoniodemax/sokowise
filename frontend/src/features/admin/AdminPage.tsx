import { useQuery } from '@tanstack/react-query'
import { Activity, Building2, MessageSquare, ShoppingCart, Users, Wallet } from 'lucide-react'

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { ErrorState } from '@/components/ui/error-state'
import { PageHeader } from '@/components/ui/page-header'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { BUSINESS_TYPES } from '@/features/auth/api'
import { MetricCard } from '@/features/dashboard/DashboardPage'
import { formatDate, formatDateTime } from '@/lib/dates'
import { formatKsh } from '@/lib/money'
import { queryKeys } from '@/lib/query-keys'

import { adminApi, type PlatformOverview } from './api'

const TYPE_LABEL: Record<string, string> = Object.fromEntries(BUSINESS_TYPES.map((t) => [t.value, t.label]))

/** "20 Aug" from a calendar date; the year is in the card title's context. */
function dayMonth(ymd: string): string {
  const [year, month, day] = ymd.split('-').map(Number)
  if (!year || !month || !day) return ymd
  return new Intl.DateTimeFormat('en-KE', { day: 'numeric', month: 'short', timeZone: 'UTC' }).format(new Date(Date.UTC(year, month - 1, day)))
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
      <PageHeader title="Admin" description="How the pilot is going across every business. Counts only; nobody's records are shown here." />
      {query.isPending ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3" aria-busy="true"><Skeleton className="h-28" /><Skeleton className="h-28" /><Skeleton className="h-28" /></div>
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
  const maxSignups = Math.max(1, ...data.signups_by_day.map((d) => d.businesses))
  return (
    <div className="space-y-6">
      <section aria-label="Totals" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        <MetricCard label="Businesses" value={String(totals.businesses)} icon={<Building2 />} hint={`${totals.businesses_active} active · ${week.new_businesses} new this week · ${month.new_businesses} this month`} />
        <MetricCard label="People" value={String(totals.users)} icon={<Users />} hint={`${totals.owners} owners · ${totals.staff} staff · ${week.users_signed_in} signed in this week`} />
        <MetricCard label="Active this week" value={String(week.businesses_with_sales)} icon={<Activity />} hint={`businesses with a sale in 7 days · ${month.businesses_with_sales} in 30 days`} />
        <MetricCard label="Sales recorded" value={String(totals.sales)} icon={<ShoppingCart />} hint={`${week.sales} this week · ${month.sales} this month`} />
        <MetricCard label="Money recorded" value={formatKsh(totals.revenue)} icon={<Wallet />} hint={`${formatKsh(week.revenue)} this week · deni outstanding ${formatKsh(totals.credit_outstanding)}`} />
        <MetricCard label="Copilot questions" value={String(totals.copilot_messages)} icon={<MessageSquare />} hint={`${totals.proposals_applied} proposals confirmed · ${totals.receipts} receipts · ${totals.mpesa_messages} M-Pesa messages`} />
      </section>
      <p className="text-xs text-muted-foreground">
        {totals.products} products · {totals.customers} customers · {totals.expenses} expenses · figures at {formatDateTime(data.generated_at, tz)}
      </p>

      <Card>
        <CardHeader>
          <CardTitle>New businesses, last 30 days</CardTitle>
          <CardDescription>Sign-ups per day ({tz}).</CardDescription>
        </CardHeader>
        <CardContent>
          <ol className="space-y-1" aria-label="Sign-ups per day">
            {data.signups_by_day.map((d) => (
              <li key={d.day} className="grid grid-cols-[4rem_1fr_2rem] items-center gap-2 text-sm">
                <span className="text-muted-foreground">{dayMonth(d.day)}</span>
                <span className="h-3 rounded bg-primary/70" style={{ width: `${(d.businesses / maxSignups) * 100}%`, minWidth: d.businesses ? '4px' : '0' }} aria-hidden="true" />
                <span className="tabular text-right">{d.businesses}</span>
              </li>
            ))}
          </ol>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Businesses</CardTitle>
          <CardDescription>Newest first. Names and counts only.</CardDescription>
        </CardHeader>
        <CardContent className="overflow-x-auto p-0 sm:p-6 sm:pt-0">
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
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.businesses.map((b) => (
                <TableRow key={b.id}>
                  <TableCell className="font-medium">{b.name}{!b.is_active && <span className="ml-2 text-xs text-muted-foreground">inactive</span>}</TableCell>
                  <TableCell>{TYPE_LABEL[b.business_type] ?? b.business_type}</TableCell>
                  <TableCell>{formatDate(b.created_at, tz)}</TableCell>
                  <TableCell className="tabular text-right">{b.products}</TableCell>
                  <TableCell className="tabular text-right">{b.sales}</TableCell>
                  <TableCell>{b.last_sale_at ? formatDateTime(b.last_sale_at, tz) : '—'}</TableCell>
                  <TableCell>{b.last_login_at ? formatDateTime(b.last_login_at, tz) : '—'}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  )
}
