import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import { toast } from 'sonner'

import { Alert } from '@/components/ui/alert'
import { BackLink } from '@/components/ui/back-link'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { PageHeader } from '@/components/ui/page-header'
import { Textarea } from '@/components/ui/textarea'
import { useAuth } from '@/features/auth/auth-context'
import type { Customer } from '@/features/customers/api'
import type { Product } from '@/features/products/api'
import { productsApi } from '@/features/products/api'
import { useProducts } from '@/features/products/hooks'
import { ProductPicker } from '@/features/products/ProductPicker'
import { ApiError } from '@/lib/api'
import { fromCents } from '@/lib/decimal'
import { describeError, fieldErrors } from '@/lib/errors'
import { useIdempotencyKey } from '@/lib/idempotency'
import { formatKsh } from '@/lib/money'
import { queryKeys } from '@/lib/query-keys'

import { salesApi, type SaleCreate } from './api'
import { cartTotals, newTender, syncSingleTender, tenderTotals, type CartLine, type Tender } from './cart'
import { CartLines } from './CartLines'
import { CustomerSection } from './CustomerSection'
import { TenderEditor } from './TenderEditor'

interface CreditLimitDetails {
  balance?: string
  credit_limit?: string
  projected_balance?: string
  owner_may_override?: boolean
}

export default function SellPage() {
  const { session } = useAuth()
  const isOwner = session?.role === 'OWNER'
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const key = useIdempotencyKey()

  const [lines, setLines] = useState<CartLine[]>([])
  const [discount, setDiscount] = useState('')
  const [customer, setCustomer] = useState<Customer | null>(null)
  const [params] = useSearchParams()
  // Opened from an M-Pesa message: the tender, amount and code come prefilled and the
  // backend links the message to this sale by its code (ARCHITECTURE §7).
  const fromMpesa = params.get('mpesa') && params.get('amount') && params.get('code') ? { id: params.get('mpesa')!, amount: params.get('amount')!, code: params.get('code')! } : null
  const [rawTenders, setTenders] = useState<Tender[]>(() => (fromMpesa ? [{ ...newTender('MPESA', fromMpesa.amount), reference: fromMpesa.code }] : [newTender('CASH')]))
  const [note, setNote] = useState('')
  const [soldAt, setSoldAt] = useState('')
  const [serverError, setServerError] = useState<string | null>(null)
  // Loose items with no product entry: an untracked product named "Other" (the setup wizard
  // adds it; an owner who skipped the wizard gets it created on first use) takes the
  // description in the note and the amount as the price.
  const otherLookup = useProducts({ q: 'Other', limit: 5 })
  const otherProduct = otherLookup.data?.find((p) => p.name.toLowerCase() === 'other' && !p.track_inventory) ?? null
  const canOfferOther = otherProduct !== null || (isOwner && otherLookup.isSuccess)
  const [otherOpen, setOtherOpen] = useState(false)
  const [otherDesc, setOtherDesc] = useState('')
  const [otherAmount, setOtherAmount] = useState('')
  const [soldAtError, setSoldAtError] = useState<string | null>(null)
  const [limitPrompt, setLimitPrompt] = useState<CreditLimitDetails | null>(null)

  const totals = cartTotals(lines, discount)
  const tenders = syncSingleTender(rawTenders, totals.total)
  const tender = tenderTotals(tenders, totals.total)
  const needsCustomer = tender.credit > 0 && !customer
  const canSubmit = lines.length > 0 && totals.total !== null && totals.total >= 0 && tender.remaining === 0 && !needsCustomer

  const ensureOther = useMutation({
    mutationFn: async () => otherProduct ?? productsApi.create({ name: 'Other', selling_price: '0.00', unit: 'other', track_inventory: false }),
    onSuccess: (base) => {
      if (!otherProduct) void queryClient.invalidateQueries({ queryKey: queryKeys.products.all })
      setLines((current) => [...current, { product: { ...base, name: otherDesc.trim() ? `Other: ${otherDesc.trim()}` : 'Other' }, quantity: '1', unit_price: otherAmount.trim() }])
      setNote((n) => (otherDesc.trim() ? [n, otherDesc.trim()].filter(Boolean).join('; ') : n))
      setOtherDesc(''); setOtherAmount(''); setOtherOpen(false); setServerError(null)
    },
    onError: (error) => setServerError(describeError(error)),
  })
  function addOther() {
    if (!otherAmount.trim()) return
    ensureOther.mutate()
  }

  function addProduct(product: Product) {
    setServerError(null)
    setLines((current) => {
      const index = current.findIndex((l) => l.product.id === product.id)
      if (index === -1) return [...current, { product, quantity: '1', unit_price: product.selling_price }]
      return current.map((l, i) => (i === index ? { ...l, quantity: String((Number(l.quantity) || 0) + 1) } : l))
    })
  }

  function buildPayload(override: boolean): SaleCreate {
    return {
      lines: lines.map((l) => ({ product_id: l.product.id, quantity: l.quantity.trim(), unit_price: l.unit_price.trim() })),
      payments: tenders.filter((t) => t.amount.trim() !== '' && Number(t.amount) > 0).map((t) => ({ method: t.method, amount: t.amount.trim(), reference: t.method === 'MPESA' && t.reference.trim() ? t.reference.trim() : null })),
      customer_id: customer?.id ?? null,
      discount_amount: discount.trim() === '' ? '0' : discount.trim(),
      note: note.trim() || null,
      ...(isOwner && soldAt ? { sold_at: new Date(soldAt).toISOString() } : {}),
      ...(override ? { credit_limit_override: true } : {}),
    }
  }

  const mutation = useMutation({
    // Same payload → same key, so a retry replays instead of duplicating (ARCHITECTURE §5.8).
    mutationFn: (payload: SaleCreate) => salesApi.create(payload, key.keyFor(payload)),
    onSuccess: (sale) => {
      key.renew()
      for (const k of [queryKeys.sales.all, queryKeys.products.all, queryKeys.inventory.all, queryKeys.customers.all, queryKeys.analytics.all]) void queryClient.invalidateQueries({ queryKey: k })
      toast.success(`Sale recorded — ${formatKsh(sale.total_amount)}`, { action: { label: 'View', onClick: () => navigate(`/sales/${sale.id}`) } })
      setLines([]); setDiscount(''); setCustomer(null); setTenders([newTender('CASH')]); setNote(''); setSoldAt(''); setServerError(null); setSoldAtError(null)
      if (fromMpesa) navigate('/mpesa')
    },
    onError: (error) => {
      if (error instanceof ApiError) {
        const details = (error.details ?? {}) as CreditLimitDetails
        switch (error.code) {
          case 'CREDIT_LIMIT_EXCEEDED':
            if (isOwner && details.owner_may_override) { setLimitPrompt(details); return }
            setServerError(`${customer?.name ?? 'This customer'} would owe ${formatKsh(details.projected_balance ?? '')}, above their limit of ${formatKsh(details.credit_limit ?? '')}. ${isOwner ? '' : 'Ask the owner to approve it, or take another payment method.'}`)
            return
          case 'INSUFFICIENT_STOCK':
            void queryClient.invalidateQueries({ queryKey: queryKeys.products.all })
            setServerError('Not enough stock for one of the items. If you do have it in the shop, add the stock first: Inventory → Restock (or set "Stock now" on the product).')
            return
          case 'SALE_BACKDATE_WINDOW':
          case 'SALE_IN_FUTURE':
            setSoldAtError(error.message)
            return
        }
        if (error.status === 403 && soldAt) { setSoldAtError('Only the owner can backdate a sale.'); return }
        const fields = fieldErrors(error)
        if (fields.sold_at) { setSoldAtError(fields.sold_at); return }
      }
      setServerError(describeError(error))
    },
  })

  const submit = (override = false) => {
    setServerError(null); setSoldAtError(null)
    mutation.mutate(buildPayload(override))
  }

  return (
    <>
      <BackLink to="/sales">Back to sales</BackLink>
      <PageHeader title="New sale" description="Add items, take payment, done." />
      {fromMpesa && <Alert className="mb-4" role="status">From an M-Pesa message: {formatKsh(fromMpesa.amount)} received, code {fromMpesa.code}. Add the items that were sold.</Alert>}
      <form onSubmit={(e) => { e.preventDefault(); if (canSubmit && !mutation.isPending) submit() }} noValidate className="grid gap-4 pb-24 lg:grid-cols-[3fr_2fr] lg:pb-0">
        {/* Phones: the total and the one action stay reachable while the cart grows. */}
        <div className="fixed inset-x-0 bottom-0 z-30 border-t border-border bg-card/95 px-4 py-3 backdrop-blur [padding-bottom:max(0.75rem,env(safe-area-inset-bottom))] lg:hidden">
          <div className="mx-auto flex max-w-6xl items-center gap-3">
            <div className="min-w-0">
              <p className="text-xs text-muted-foreground">{lines.length === 0 ? 'No items yet' : `${lines.length} ${lines.length === 1 ? 'item' : 'items'} · ${tender.remaining === 0 ? 'fully paid' : tender.remaining === null ? 'check amounts' : tender.remaining > 0 ? 'still to pay' : 'over paid'}`}</p>
              <p className="tabular text-lg font-semibold">{totals.total === null || totals.total < 0 ? '—' : formatKsh(fromCents(totals.total))}</p>
            </div>
            <Button type="submit" size="lg" className="ml-auto" disabled={!canSubmit} loading={mutation.isPending}>Record sale</Button>
          </div>
        </div>
        <div className="space-y-4">
          <Card>
            <CardHeader><CardTitle>Items</CardTitle></CardHeader>
            <CardContent className="space-y-4">
              <ProductPicker onPick={addProduct} autoFocus placeholder="Search products to add" />
              {canOfferOther && !otherOpen && (
                <Button type="button" variant="outline" size="sm" onClick={() => setOtherOpen(true)}>Other item (no product)</Button>
              )}
              {canOfferOther && otherOpen && (
                <div className="flex flex-col gap-2 rounded-lg border border-dashed border-border p-3 sm:flex-row sm:items-end">
                  <label className="grid flex-1 gap-1 text-sm"><span className="text-muted-foreground">What was it?</span><Input aria-label="Other item description" value={otherDesc} onChange={(e) => setOtherDesc(e.target.value)} placeholder="e.g. 2 scoops of rice" /></label>
                  <label className="grid gap-1 text-sm"><span className="text-muted-foreground">Amount (KSh)</span><Input aria-label="Other item amount" inputMode="decimal" value={otherAmount} onChange={(e) => setOtherAmount(e.target.value)} className="w-32" /></label>
                  <div className="flex gap-2">
                    <Button type="button" onClick={addOther} loading={ensureOther.isPending} disabled={!/^\d+(\.\d{1,2})?$/.test(otherAmount.trim()) || Number(otherAmount) <= 0}>Add</Button>
                    <Button type="button" variant="ghost" onClick={() => setOtherOpen(false)}>Cancel</Button>
                  </div>
                </div>
              )}
              <CartLines lines={lines} invalidLine={totals.invalidLine} onChange={(i, patch) => setLines((c) => c.map((l, j) => (j === i ? { ...l, ...patch } : l)))} onRemove={(i) => setLines((c) => c.filter((_, j) => j !== i))} />
            </CardContent>
          </Card>
        </div>
        <div className="space-y-4">
          <Card>
            <CardHeader><CardTitle>Customer</CardTitle></CardHeader>
            <CardContent><CustomerSection customer={customer} creditCents={tender.credit} onChange={(c) => { setCustomer(c); setServerError(null) }} /></CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Payment</CardTitle></CardHeader>
            <CardContent className="space-y-4">
              <dl className="space-y-1 text-sm">
                <div className="flex justify-between"><dt className="text-muted-foreground">Subtotal</dt><dd className="tabular">{totals.subtotal === null ? '—' : formatKsh(fromCents(totals.subtotal))}</dd></div>
                <div className="flex items-center justify-between gap-3">
                  <dt><label htmlFor="discount" className="text-muted-foreground">Discount</label></dt>
                  <dd><Input id="discount" inputMode="decimal" placeholder="0" value={discount} invalid={totals.discount === null || (totals.total !== null && totals.total < 0)} onChange={(e) => setDiscount(e.target.value)} className="h-9 w-28 text-right" /></dd>
                </div>
                {totals.total !== null && totals.total < 0 && <p className="text-xs text-destructive" role="alert">The discount is more than the subtotal.</p>}
                <div className="flex justify-between border-t border-border pt-2 text-base font-semibold"><dt>Total</dt><dd className="tabular">{totals.total === null ? '—' : formatKsh(fromCents(totals.total))}</dd></div>
              </dl>
              <TenderEditor tenders={tenders} totals={tender} total={totals.total} hasCustomer={!!customer} onChange={setTenders} />
              <Field id="note" label="Note" optional>
                <Textarea id="note" rows={2} className="min-h-0" maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} />
              </Field>
              {isOwner && (
                <Field id="sold_at" label="Sold at" optional hint="Leave empty for now. Backdating is limited by your settings." error={soldAtError ?? undefined}>
                  <Input id="sold_at" type="datetime-local" value={soldAt} invalid={!!soldAtError} onChange={(e) => { setSoldAt(e.target.value); setSoldAtError(null) }} />
                </Field>
              )}
              {serverError && <Alert variant="destructive" role="alert">{serverError}</Alert>}
              {needsCustomer && <p className="text-sm text-destructive" role="alert">Credit sales need a customer.</p>}
              <div className="hidden lg:block">
                <Button type="submit" size="lg" className="w-full" disabled={!canSubmit} loading={mutation.isPending}>
                  {totals.total === null || totals.total < 0 ? 'Record sale' : `Record sale · ${formatKsh(fromCents(totals.total))}`}
                </Button>
                <p className="mt-2 text-center text-xs text-muted-foreground">Sales cannot be edited afterwards; the owner can void one by mistake.</p>
              </div>
            </CardContent>
          </Card>
        </div>
      </form>
      <ConfirmDialog
        open={limitPrompt !== null}
        onOpenChange={(o) => !o && setLimitPrompt(null)}
        title="Over the credit limit — allow anyway?"
        description={`${customer?.name ?? 'This customer'} owes ${formatKsh(limitPrompt?.balance ?? '')} and would owe ${formatKsh(limitPrompt?.projected_balance ?? '')} after this sale, above their limit of ${formatKsh(limitPrompt?.credit_limit ?? '')}. Your approval is recorded.`}
        confirmLabel="Allow this sale"
        onConfirm={() => { setLimitPrompt(null); submit(true) }}
      />
    </>
  )
}
