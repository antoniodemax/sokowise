import type { UseQueryResult } from '@tanstack/react-query'
import { Link } from 'react-router'

import { Badge } from '@/components/ui/badge'
import { ErrorState } from '@/components/ui/error-state'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useAuth } from '@/features/auth/auth-context'
import { formatDateTime } from '@/lib/dates'
import { formatKsh, formatQuantity } from '@/lib/money'

import { MOVEMENT_LABELS, type Movement } from './api'

const TONE: Record<Movement['movement_type'], 'success' | 'destructive' | 'info' | 'warning' | 'neutral'> = {
  INITIAL: 'info',
  RESTOCK: 'success',
  SALE: 'neutral',
  SALE_REVERSAL: 'warning',
  ADJUSTMENT: 'warning',
}

interface MovementsTableProps {
  query: UseQueryResult<Movement[]>
  /** Product column shown when listing across products. */
  productNames?: Map<string, string>
  compact?: boolean
}

export function MovementsTable({ query, productNames, compact }: MovementsTableProps) {
  const { session } = useAuth()
  const tz = session?.business.timezone ?? 'Africa/Nairobi'
  if (query.isPending) return <div className="space-y-2" aria-busy="true"><Skeleton className="h-10" /><Skeleton className="h-10" /><Skeleton className="h-10" /></div>
  if (query.isError) return <ErrorState error={query.error} title="Could not load stock movements" onRetry={() => query.refetch()} />
  if (query.data.length === 0) return <p className="rounded-lg border border-dashed border-border px-4 py-6 text-center text-sm text-muted-foreground">No stock movements yet.</p>
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>When</TableHead>
          {productNames && <TableHead>Product</TableHead>}
          <TableHead>What</TableHead>
          <TableHead className="text-right">Change</TableHead>
          <TableHead className="text-right">After</TableHead>
          {!compact && <TableHead className="hidden text-right md:table-cell">Unit cost</TableHead>}
        </TableRow>
      </TableHeader>
      <TableBody>
        {query.data.map((m) => (
          <TableRow key={m.id}>
            <TableCell className="whitespace-nowrap text-muted-foreground">{formatDateTime(m.occurred_at, tz)}</TableCell>
            {productNames && <TableCell>{productNames.get(m.product_id) ?? '—'}</TableCell>}
            <TableCell>
              <Badge variant={TONE[m.movement_type]}>{MOVEMENT_LABELS[m.movement_type]}</Badge>
              {(m.reason || m.supplier_name) && <span className="mt-1 block text-xs text-muted-foreground">{[m.supplier_name, m.reason].filter(Boolean).join(' · ')}</span>}
              {m.sale_id && <Link to={`/sales/${m.sale_id}`} className="mt-1 inline-flex min-h-8 items-center text-xs text-primary hover:underline">View sale</Link>}
            </TableCell>
            <TableCell className={`tabular text-right font-medium ${m.quantity_delta.startsWith('-') ? 'text-destructive' : 'text-success'}`}>
              {m.quantity_delta.startsWith('-') ? '' : '+'}{formatQuantity(m.quantity_delta)}
            </TableCell>
            <TableCell className="tabular text-right">{formatQuantity(m.quantity_after)}</TableCell>
            {!compact && <TableCell className="tabular hidden text-right text-muted-foreground md:table-cell">{m.unit_cost ? formatKsh(m.unit_cost) : '—'}</TableCell>}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
