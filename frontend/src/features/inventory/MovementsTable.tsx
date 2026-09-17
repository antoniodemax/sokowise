import type { UseQueryResult } from '@tanstack/react-query'
import { Link } from 'react-router'

import { Badge } from '@/components/ui/badge'
import { When } from '@/components/ui/when'
import { ErrorState } from '@/components/ui/error-state'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useAuth } from '@/features/auth/auth-context'
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
          {productNames && <TableHead className="hidden sm:table-cell">Product</TableHead>}
          <TableHead>What</TableHead>
          <TableHead className="text-right">Change</TableHead>
          <TableHead className="hidden text-right sm:table-cell">After</TableHead>
          {!compact && <TableHead className="hidden text-right md:table-cell">Unit cost</TableHead>}
        </TableRow>
      </TableHeader>
      <TableBody>
        {query.data.map((m) => (
          <TableRow key={m.id}>
            <TableCell className="text-muted-foreground"><When iso={m.occurred_at} timeZone={tz} /></TableCell>
            {productNames && <TableCell className="hidden sm:table-cell">{productNames.get(m.product_id) ?? '—'}</TableCell>}
            <TableCell>
              {productNames && <span className="mb-1 block text-sm font-medium sm:hidden">{productNames.get(m.product_id) ?? '—'}</span>}
              <Badge variant={TONE[m.movement_type]}>{MOVEMENT_LABELS[m.movement_type]}</Badge>
              {(m.reason || m.supplier_name) && <span className="mt-1 block text-xs text-muted-foreground">{[m.supplier_name, m.reason].filter(Boolean).join(' · ')}</span>}
              {m.sale_id && <Link to={`/sales/${m.sale_id}`} className="mt-1 inline-flex min-h-8 items-center text-xs text-primary hover:underline">View sale</Link>}
            </TableCell>
            <TableCell className={`tabular text-right font-medium ${m.quantity_delta.startsWith('-') ? 'text-destructive' : 'text-success'}`}>
              {m.quantity_delta.startsWith('-') ? '' : '+'}{formatQuantity(m.quantity_delta)}
              <span className="block text-xs font-normal text-muted-foreground sm:hidden">→ {formatQuantity(m.quantity_after)}</span>
            </TableCell>
            <TableCell className="tabular hidden text-right sm:table-cell">{formatQuantity(m.quantity_after)}</TableCell>
            {!compact && <TableCell className="tabular hidden text-right text-muted-foreground md:table-cell">{m.unit_cost ? formatKsh(m.unit_cost) : '—'}</TableCell>}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
