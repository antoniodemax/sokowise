import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Ban } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { toast } from 'sonner'

import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { ErrorState } from '@/components/ui/error-state'
import { Field } from '@/components/ui/field'
import { PageHeader } from '@/components/ui/page-header'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'
import { useAuth } from '@/features/auth/auth-context'
import { useCustomer } from '@/features/customers/hooks'
import { formatDateTime } from '@/lib/dates'
import { describeError } from '@/lib/errors'
import { formatKsh, formatQuantity } from '@/lib/money'
import { queryKeys } from '@/lib/query-keys'

import { PAYMENT_LABELS, salesApi } from './api'
import { useSale } from './hooks'

export default function SaleDetailPage() {
  const { saleId } = useParams()
  const { session } = useAuth()
  const isOwner = session?.role === 'OWNER'
  const tz = session?.business.timezone ?? 'Africa/Nairobi'
  const queryClient = useQueryClient()
  const sale = useSale(saleId)
  const customer = useCustomer(sale.data?.customer_id ?? undefined)
  const [voiding, setVoiding] = useState(false)
  const [reason, setReason] = useState('')
  const [voidError, setVoidError] = useState<string | null>(null)

  const voidMutation = useMutation({
    mutationFn: () => salesApi.void(saleId!, reason.trim()),
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.sales.detail(saleId!), updated)
      for (const k of [queryKeys.sales.all, queryKeys.products.all, queryKeys.inventory.all, queryKeys.customers.all, queryKeys.analytics.all]) void queryClient.invalidateQueries({ queryKey: k })
      toast.success('Sale voided. Stock and any credit have been put back.')
      setVoiding(false)
      setReason('')
    },
    onError: (error) => setVoidError(describeError(error)),
  })

  if (sale.isPending) return <div className="space-y-4"><Skeleton className="h-8 w-64" /><Skeleton className="h-40" /></div>
  if (sale.isError) return <ErrorState error={sale.error} title="Could not load this sale" onRetry={() => sale.refetch()} />
  const s = sale.data
  const voided = s.status === 'VOIDED'

  return (
    <>
      <Link to="/sales" className="mb-4 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" aria-hidden="true" /> All sales</Link>
      <PageHeader
        title={<span className="flex flex-wrap items-center gap-2">Sale {voided ? <Badge variant="destructive">Voided</Badge> : <Badge variant="success">Completed</Badge>}</span>}
        description={formatDateTime(s.sold_at, tz)}
        actions={isOwner && !voided ? <Button variant="destructive" onClick={() => setVoiding(true)}><Ban aria-hidden="true" /> Void sale</Button> : undefined}
      />
      {voided && (
        <Alert variant="warning" title="This sale was voided" className="mb-4">
          {formatDateTime(s.voided_at, tz)} — {s.void_reason ?? 'no reason recorded'}. Stock and credit were reversed; it is excluded from reports.
        </Alert>
      )}
      <div className="grid gap-4 lg:grid-cols-[3fr_2fr]">
        <Card>
          <CardHeader><CardTitle>Items</CardTitle></CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Product</TableHead>
                  <TableHead className="text-right">Qty</TableHead>
                  <TableHead className="hidden text-right sm:table-cell">Price</TableHead>
                  <TableHead className="text-right">Line</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {s.items.map((item) => (
                  <TableRow key={item.id}>
                    <TableCell>
                      <Link to={`/products/${item.product_id}`} className="font-medium hover:underline">{item.product_name}</Link>
                      {item.default_unit_price !== null && item.default_unit_price !== item.unit_price && <span className="block text-xs text-muted-foreground">usual price {formatKsh(item.default_unit_price)}</span>}
                    </TableCell>
                    <TableCell className="tabular text-right">{formatQuantity(item.quantity)}</TableCell>
                    <TableCell className="tabular hidden text-right sm:table-cell">{formatKsh(item.unit_price)}</TableCell>
                    <TableCell className="tabular text-right">{formatKsh(item.line_total)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <dl className="mt-4 space-y-1 text-sm">
              <div className="flex justify-between"><dt className="text-muted-foreground">Subtotal</dt><dd className="tabular">{formatKsh(s.subtotal)}</dd></div>
              {Number(s.discount_amount) > 0 && <div className="flex justify-between"><dt className="text-muted-foreground">Discount</dt><dd className="tabular">−{formatKsh(s.discount_amount)}</dd></div>}
              <div className="flex justify-between border-t border-border pt-2 text-base font-semibold"><dt>Total</dt><dd className="tabular">{formatKsh(s.total_amount)}</dd></div>
            </dl>
          </CardContent>
        </Card>
        <div className="space-y-4">
          <Card>
            <CardHeader><CardTitle>Payment</CardTitle></CardHeader>
            <CardContent>
              <ul className="space-y-2 text-sm">
                {s.payments.map((p) => (
                  <li key={p.id} className="flex items-center justify-between gap-3">
                    <span>
                      {PAYMENT_LABELS[p.method]}
                      {p.method === 'CREDIT' && <span className="ml-1 text-xs text-muted-foreground">(owed by customer)</span>}
                      {p.reference && <span className="block text-xs text-muted-foreground">Code {p.reference} · not verified</span>}
                    </span>
                    <span className="tabular font-medium">{formatKsh(p.amount)}</span>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Details</CardTitle></CardHeader>
            <CardContent>
              <dl className="space-y-2 text-sm">
                <div className="flex justify-between gap-3"><dt className="text-muted-foreground">Customer</dt><dd>{s.customer_id ? <Link to={`/customers/${s.customer_id}`} className="font-medium text-primary hover:underline">{customer.data?.name ?? 'View customer'}</Link> : 'Walk-in'}</dd></div>
                <div className="flex justify-between gap-3"><dt className="text-muted-foreground">Recorded</dt><dd>{formatDateTime(s.created_at, tz)}</dd></div>
                {s.note && <div><dt className="text-muted-foreground">Note</dt><dd className="mt-1 whitespace-pre-wrap">{s.note}</dd></div>}
              </dl>
            </CardContent>
          </Card>
        </div>
      </div>
      <Dialog open={voiding} onOpenChange={(o) => { if (!voidMutation.isPending) { setVoiding(o); setVoidError(null) } }}>
        <DialogContent>
          <form onSubmit={(e) => { e.preventDefault(); if (reason.trim()) voidMutation.mutate() }} className="space-y-4">
            <DialogHeader>
              <DialogTitle>Void this sale?</DialogTitle>
              <DialogDescription>Stock goes back, any credit is removed from the customer's account, and the sale is excluded from reports. This cannot be undone.</DialogDescription>
            </DialogHeader>
            {voidError && <Alert variant="destructive">{voidError}</Alert>}
            <Field id="void-reason" label="Reason" error={reason.trim() ? undefined : undefined}>
              <Textarea id="void-reason" rows={2} autoFocus maxLength={255} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Rang up the wrong item" />
            </Field>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setVoiding(false)} disabled={voidMutation.isPending}>Keep sale</Button>
              <Button type="submit" variant="destructive" disabled={!reason.trim()} loading={voidMutation.isPending}>Void sale</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  )
}
