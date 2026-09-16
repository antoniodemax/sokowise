import { Plus, Receipt } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router'

import { Badge } from '@/components/ui/badge'
import { buttonVariants } from '@/components/ui/button-variants'
import { EmptyState } from '@/components/ui/empty-state'
import { ErrorState } from '@/components/ui/error-state'
import { Input } from '@/components/ui/input'
import { PageHeader } from '@/components/ui/page-header'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useAuth } from '@/features/auth/auth-context'
import { formatDateTime, localDate, zonedDayRange } from '@/lib/dates'
import { formatKsh } from '@/lib/money'

import { useSales } from './hooks'
import { tenderSummary } from './summary'

export default function SalesPage() {
  const { session } = useAuth()
  const isOwner = session?.role === 'OWNER'
  const tz = session?.business.timezone ?? 'Africa/Nairobi'
  const navigate = useNavigate()
  const today = localDate(new Date(), tz)
  const [dateFrom, setDateFrom] = useState(today)
  const [dateTo, setDateTo] = useState(today)
  // The backend filters on instants (sold_at >= from, < until), so calendar dates become the
  // business-timezone day boundaries here.
  const range = isOwner && dateFrom && dateTo && dateFrom <= dateTo ? zonedDayRange(dateFrom, dateTo, tz) : null
  const sales = useSales(range ? { date_from: range.from, date_to: range.to, limit: 200 } : { limit: 200 })

  return (
    <>
      <PageHeader title="Sales" description={isOwner ? 'Every sale recorded, newest first.' : 'Your sales from today.'} actions={<Link to="/sales/new" className={buttonVariants()}><Plus aria-hidden="true" /> New sale</Link>} />
      {isOwner && (
        <div className="mb-4 grid grid-cols-2 gap-3 sm:max-w-md">
          <div>
            <label htmlFor="date_from" className="mb-1 block text-xs text-muted-foreground">From</label>
            <Input id="date_from" type="date" value={dateFrom} max={dateTo || undefined} onChange={(e) => setDateFrom(e.target.value)} />
          </div>
          <div>
            <label htmlFor="date_to" className="mb-1 block text-xs text-muted-foreground">To</label>
            <Input id="date_to" type="date" value={dateTo} min={dateFrom || undefined} onChange={(e) => setDateTo(e.target.value)} />
          </div>
        </div>
      )}
      {sales.isPending ? (
        <div className="space-y-2" aria-busy="true"><Skeleton className="h-12" /><Skeleton className="h-12" /><Skeleton className="h-12" /></div>
      ) : sales.isError ? (
        <ErrorState error={sales.error} title="Could not load sales" onRetry={() => sales.refetch()} />
      ) : sales.data.length === 0 ? (
        <EmptyState icon={Receipt} title="No sales here" description={isOwner ? 'Nothing was sold in this period.' : 'You have not recorded a sale today.'} action={<Link to="/sales/new" className={buttonVariants()}><Plus aria-hidden="true" /> Record a sale</Link>} />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>When</TableHead>
              <TableHead>Items</TableHead>
              <TableHead className="hidden sm:table-cell">Paid by</TableHead>
              <TableHead className="text-right">Total</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {sales.data.map((sale) => (
              <TableRow key={sale.id} className="cursor-pointer" onClick={() => navigate(`/sales/${sale.id}`)}>
                <TableCell className="whitespace-nowrap">
                  <Link to={`/sales/${sale.id}`} className="font-medium hover:underline" onClick={(e) => e.stopPropagation()}>{formatDateTime(sale.sold_at, tz)}</Link>
                  {sale.status === 'VOIDED' && <Badge variant="destructive" className="ml-2">Voided</Badge>}
                </TableCell>
                <TableCell className="max-w-64 truncate text-muted-foreground">{sale.items.map((i) => `${i.quantity.replace(/\.?0+$/, '')}× ${i.product_name}`).join(', ')}</TableCell>
                <TableCell className="hidden text-muted-foreground sm:table-cell">{tenderSummary(sale)}</TableCell>
                <TableCell className={`tabular text-right font-semibold ${sale.status === 'VOIDED' ? 'text-muted-foreground line-through' : ''}`}>{formatKsh(sale.total_amount)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </>
  )
}
