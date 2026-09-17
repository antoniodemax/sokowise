import { HandCoins, SlidersHorizontal } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router'

import { BackLink } from '@/components/ui/back-link'
import { Badge } from '@/components/ui/badge'
import { When } from '@/components/ui/when'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { ErrorState } from '@/components/ui/error-state'
import { PageHeader } from '@/components/ui/page-header'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useAuth } from '@/features/auth/auth-context'
import { formatKsh } from '@/lib/money'

import type { LedgerEntryType } from './api'
import { BalanceBadge } from './BalanceBadge'
import { useCustomer, useLedger } from './hooks'
import { AdjustmentDialog, RepaymentDialog } from './LedgerDialogs'

const ENTRY_LABELS: Record<LedgerEntryType, string> = { CHARGE: 'Credit sale', REPAYMENT: 'Repayment', REVERSAL: 'Sale voided', ADJUSTMENT: 'Adjustment' }
const ENTRY_TONE: Record<LedgerEntryType, 'warning' | 'success' | 'info' | 'neutral'> = { CHARGE: 'warning', REPAYMENT: 'success', REVERSAL: 'info', ADJUSTMENT: 'neutral' }

export default function CustomerDetailPage() {
  const { customerId } = useParams()
  const { session } = useAuth()
  const isOwner = session?.role === 'OWNER'
  const tz = session?.business.timezone ?? 'Africa/Nairobi'
  const customer = useCustomer(customerId)
  const ledger = useLedger(customerId)
  const [dialog, setDialog] = useState<'repay' | 'adjust' | null>(null)

  if (customer.isPending) return <div className="space-y-4"><Skeleton className="h-8 w-64" /><Skeleton className="h-32" /></div>
  if (customer.isError) return <><BackLink to="/customers">All customers</BackLink><ErrorState error={customer.error} title="Could not load this customer" onRetry={() => customer.refetch()} /></>
  const c = customer.data
  const owes = Number(c.balance) > 0

  return (
    <>
      <BackLink to="/customers">All customers</BackLink>
      <PageHeader
        title={c.name}
        description={[c.phone, c.is_active ? null : 'archived'].filter(Boolean).join(' · ') || 'No phone number'}
        actions={
          <>
            <Button onClick={() => setDialog('repay')} disabled={!c.is_active}><HandCoins aria-hidden="true" /> Record repayment</Button>
            {isOwner && <Button variant="outline" onClick={() => setDialog('adjust')} disabled={!c.is_active}><SlidersHorizontal aria-hidden="true" /> Adjust balance</Button>}
          </>
        }
      />
      <div className="grid gap-4 md:grid-cols-3">
        <Card className={owes ? 'border-warning/40' : undefined}>
          <CardContent className="p-5">
            <p className="text-sm text-muted-foreground">{owes ? 'Owes you' : Number(c.balance) < 0 ? 'Credit in their favour' : 'Balance'}</p>
            <p className={`tabular mt-1 text-2xl font-semibold ${owes ? 'text-warning' : ''}`}>{formatKsh(c.balance.replace('-', ''))}</p>
            <div className="mt-2">{<BalanceBadge balance={c.balance} />}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-5">
            <p className="text-sm text-muted-foreground">Credit limit</p>
            <p className="tabular mt-1 text-2xl font-semibold">{c.credit_limit === null ? 'No limit' : formatKsh(c.credit_limit)}</p>
            {c.credit_limit !== null && Number(c.credit_limit) > 0 && (
              <p className="mt-1 text-xs text-muted-foreground">
                {Number(c.credit_limit) - Number(c.balance) > 0 ? `Can still buy on credit up to ${formatKsh(String(Math.max(0, Number(c.credit_limit) - Number(c.balance)).toFixed(2)))}` : 'At the limit'}
              </p>
            )}
            {c.credit_limit !== null && Number(c.credit_limit) === 0 && <p className="mt-1 text-xs text-muted-foreground">No credit sales for this customer.</p>}
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-5">
            <p className="text-sm text-muted-foreground">Notes</p>
            <p className="mt-1 text-sm">{c.notes ?? <span className="text-muted-foreground">—</span>}</p>
          </CardContent>
        </Card>
      </div>
      <Card className="mt-4">
        <CardHeader>
          <CardTitle>Account history</CardTitle>
          <CardDescription>Credit sales add to what they owe; repayments and voids reduce it.</CardDescription>
        </CardHeader>
        <CardContent>
          {ledger.isPending ? (
            <div className="space-y-2" aria-busy="true"><Skeleton className="h-10" /><Skeleton className="h-10" /></div>
          ) : ledger.isError ? (
            <ErrorState error={ledger.error} title="Could not load the account history" onRetry={() => ledger.refetch()} />
          ) : ledger.data.entries.length === 0 ? (
            <p className="rounded-lg border border-dashed border-border px-4 py-6 text-center text-sm text-muted-foreground">No credit activity yet.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>When</TableHead>
                  <TableHead>What</TableHead>
                  <TableHead className="text-right">Amount</TableHead>
                  <TableHead className="hidden text-right sm:table-cell">Owed after</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {ledger.data.entries.map((entry) => (
                  <TableRow key={entry.id}>
                    <TableCell className="text-muted-foreground"><When iso={entry.occurred_at} timeZone={tz} /></TableCell>
                    <TableCell>
                      <Badge variant={ENTRY_TONE[entry.entry_type]}>{ENTRY_LABELS[entry.entry_type]}</Badge>
                      {(entry.payment_method || entry.reference || entry.reason) && <span className="mt-1 block text-xs text-muted-foreground">{[entry.payment_method === 'MPESA' ? 'M-Pesa' : entry.payment_method === 'CASH' ? 'Cash' : null, entry.reference, entry.reason].filter(Boolean).join(' · ')}</span>}
                      {entry.sale_id && <Link to={`/sales/${entry.sale_id}`} className="mt-1 block text-xs text-primary hover:underline">View sale</Link>}
                    </TableCell>
                    <TableCell className={`tabular text-right font-medium ${entry.amount.startsWith('-') ? 'text-success' : 'text-warning'}`}>{entry.amount.startsWith('-') ? '−' : '+'}{formatKsh(entry.amount.replace('-', ''), { bare: true })}
                      <span className="block text-xs font-normal text-muted-foreground sm:hidden">owes {formatKsh(entry.balance_after)}</span>
                    </TableCell>
                    <TableCell className="tabular hidden text-right sm:table-cell">{formatKsh(entry.balance_after)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
      <RepaymentDialog customer={c} open={dialog === 'repay'} onOpenChange={(o) => !o && setDialog(null)} />
      {isOwner && <AdjustmentDialog customer={c} open={dialog === 'adjust'} onOpenChange={(o) => !o && setDialog(null)} />}
    </>
  )
}
