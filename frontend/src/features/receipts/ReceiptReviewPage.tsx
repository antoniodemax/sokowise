import { useMutation, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Check, Image as ImageIcon, RefreshCw, X } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router'
import { toast } from 'sonner'

import { Alert } from '@/components/ui/alert'
import { BackLink } from '@/components/ui/back-link'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { buttonVariants } from '@/components/ui/button-variants'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { ErrorState } from '@/components/ui/error-state'
import { Input } from '@/components/ui/input'
import { PageHeader } from '@/components/ui/page-header'
import { Skeleton } from '@/components/ui/skeleton'
import { Spinner } from '@/components/ui/spinner'
import { useAuth } from '@/features/auth/auth-context'
import { useProducts } from '@/features/products/hooks'
import { ProductPicker } from '@/features/products/ProductPicker'
import { formatCalendarDate, formatDateTime } from '@/lib/dates'
import { fromCents, lineCents, toCents } from '@/lib/decimal'
import { formatKsh, formatQuantity } from '@/lib/money'
import { queryKeys } from '@/lib/query-keys'
import { cn } from '@/lib/utils'

import { receiptsApi, type Receipt, type ReceiptLine } from './api'
import { receiptKeys, useReceipt } from './hooks'
import { describeReceiptError, STATUS_LABELS, WARNING_TEXT } from './status'

interface Decision {
  include: boolean
  productId: string | null
  quantity: string
  unitCost: string
  updateCost: boolean
}

function initialDecisions(receipt: Receipt): Record<string, Decision> {
  return Object.fromEntries(
    receipt.lines.map((line) => [
      line.id,
      {
        include: line.match_status === 'MATCHED',
        productId: line.matched_product_id,
        quantity: formatQuantity(line.extracted_quantity).replace(/,/g, ''),
        unitCost: line.extracted_unit_cost,
        updateCost: false,
      },
    ]),
  )
}

export default function ReceiptReviewPage() {
  const { receiptId } = useParams()
  const { session } = useAuth()
  const tz = session?.business.timezone ?? 'Africa/Nairobi'
  const queryClient = useQueryClient()
  const receipt = useReceipt(receiptId)
  const [showImage, setShowImage] = useState(false)

  const products = useProducts({ limit: 500 })
  const productById = useMemo(() => new Map((products.data ?? []).map((p) => [p.id, p])), [products.data])
  const data = receipt.data
  // The detail is written from the mutation results; only the list and stock caches refetch.
  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: receiptKeys.list })
    void queryClient.invalidateQueries({ queryKey: queryKeys.products.all })
    void queryClient.invalidateQueries({ queryKey: queryKeys.inventory.all })
  }
  const process = useMutation({
    mutationFn: () => receiptsApi.process(receiptId!),
    onSuccess: (updated) => { queryClient.setQueryData(receiptKeys.detail(receiptId!), updated); invalidate() },
    onError: () => invalidate(),
  })
  const cancel = useMutation({
    mutationFn: () => receiptsApi.cancel(receiptId!),
    onSuccess: (updated) => { queryClient.setQueryData(receiptKeys.detail(receiptId!), updated); invalidate(); toast.success('Receipt cancelled') },
  })

  if (receipt.isPending) return <div className="space-y-4"><Skeleton className="h-8 w-64" /><Skeleton className="h-40" /></div>
  if (receipt.isError || !data) return <><BackLink to="/inventory/receipts">Supplier receipts</BackLink><ErrorState error={receipt.error} title="Could not load this receipt" onRetry={() => receipt.refetch()} /></>

  const status = STATUS_LABELS[data.status]
  const reviewable = data.status === 'READY_FOR_REVIEW'

  return (
    <>
      <BackLink to="/inventory/receipts">Supplier receipts</BackLink>
      <PageHeader
        title={<span className="flex flex-wrap items-center gap-2">{data.supplier_name ?? 'Supplier receipt'} <Badge variant={status.variant}>{status.label}</Badge></span>}
        description={[data.receipt_number ? `No. ${data.receipt_number}` : null, data.receipt_date ? formatCalendarDate(data.receipt_date) : null, `uploaded ${formatDateTime(data.created_at, tz)}`].filter(Boolean).join(' · ')}
        actions={
          <>
            <Button variant="outline" onClick={() => setShowImage(true)}><ImageIcon aria-hidden="true" /> View photo</Button>
            {(data.status === 'UPLOADED' || data.status === 'FAILED') && <Button onClick={() => process.mutate()} loading={process.isPending}><RefreshCw aria-hidden="true" /> {data.status === 'FAILED' ? 'Try reading again' : 'Read receipt'}</Button>}
            {data.status !== 'CONFIRMED' && data.status !== 'CANCELLED' && <Button variant="ghost" onClick={() => cancel.mutate()} loading={cancel.isPending}><X aria-hidden="true" /> Cancel</Button>}
          </>
        }
      />

      {process.isPending && <p className="mb-4 flex items-center gap-2 text-sm text-muted-foreground"><Spinner label="Reading the receipt…" /></p>}
      {process.isError && <Alert variant="destructive" className="mb-4" role="alert">{describeReceiptError(process.error)}</Alert>}
      {data.status === 'FAILED' && !process.isError && <Alert variant="destructive" className="mb-4" title="This receipt could not be read">{data.extraction_error === 'NO_LINES' ? 'No products were found on the photo. Try a clearer, closer photo in good light.' : data.extraction_error === 'RECEIPT_AI_NOT_CONFIGURED' ? 'Receipt reading is not set up on this server yet.' : 'Try reading it again, or take a new photo.'}</Alert>}
      {data.status === 'UPLOADED' && !process.isPending && <Alert variant="info" className="mb-4">The photo is saved. Read it to see the products on it.</Alert>}
      {data.status === 'CONFIRMED' && (
        <Alert variant="success" className="mb-4" title="Stock has been added">
          {data.lines.filter((l) => l.review_status === 'APPLIED').length} {data.lines.filter((l) => l.review_status === 'APPLIED').length === 1 ? 'product was' : 'products were'} restocked on {formatDateTime(data.confirmed_at, tz)}. <Link to="/inventory" className="font-medium underline">See stock movements</Link>.
        </Alert>
      )}
      {data.warnings.length > 0 && data.status !== 'CANCELLED' && (
        <Alert variant="warning" className="mb-4" title="Check these before confirming">
          <ul className="list-disc pl-4">{data.warnings.map((w) => <li key={w}>{WARNING_TEXT[w] ?? w}</li>)}</ul>
        </Alert>
      )}

      {reviewable ? (
        <ReviewSection key={`${data.id}:${data.extracted_at ?? ''}`} receipt={data} onConfirmed={(updated) => { queryClient.setQueryData(receiptKeys.detail(data.id), updated); invalidate() }} />
      ) : data.lines.length > 0 ? (
        <Card>
          <CardHeader><CardTitle>Lines</CardTitle><CardDescription>What was read from the receipt.</CardDescription></CardHeader>
          <CardContent>
            <ul className="space-y-3" aria-label="Receipt lines">
              {data.lines.map((line) => <ReviewLine key={line.id} line={line} decision={undefined} reviewable={false} productName={(id) => (id ? productById.get(id)?.name ?? 'Product' : null)} onChange={() => {}} onPick={() => {}} />)}
            </ul>
          </CardContent>
        </Card>
      ) : null}

      <Dialog open={showImage} onOpenChange={setShowImage}>
        <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Receipt photo</DialogTitle>
            <DialogDescription>{data.original_filename ?? 'The uploaded image'}</DialogDescription>
          </DialogHeader>
          <ReceiptImage id={data.id} />
        </DialogContent>
      </Dialog>
    </>
  )
}

/** Owns the owner's decisions for a reviewable receipt; remounts when the extraction changes. */
function ReviewSection({ receipt, onConfirmed }: { receipt: Receipt; onConfirmed: (updated: Receipt) => void }) {
  const products = useProducts({ limit: 500 })
  const productById = useMemo(() => new Map((products.data ?? []).map((p) => [p.id, p])), [products.data])
  const [decisions, setDecisions] = useState<Record<string, Decision>>(() => initialDecisions(receipt))
  const [picking, setPicking] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)
  const update = (id: string, patch: Partial<Decision>) => setDecisions((c) => ({ ...c, [id]: { ...c[id], ...patch } }))

  const included = Object.entries(decisions).filter(([, d]) => d.include)
  const problems = included.filter(([, d]) => !d.productId || lineCents(d.quantity, d.unitCost) === null || Number(d.quantity) <= 0 || toCents(d.unitCost) === null)
  const totalCents = included.reduce((sum, [, d]) => sum + (lineCents(d.quantity, d.unitCost) ?? 0), 0)
  const totalQty = included.reduce((sum, [, d]) => sum + (Number(d.quantity) || 0), 0)

  const confirm = useMutation({
    mutationFn: () =>
      receiptsApi.confirm(receipt.id, {
        lines: included.map(([id, d]) => ({ line_id: id, product_id: d.productId!, quantity: d.quantity.trim(), unit_cost: d.unitCost.trim(), update_cost_price: d.updateCost })),
        supplier_name: receipt.supplier_name,
      }),
    onSuccess: (result) => {
      onConfirmed(result.receipt)
      toast.success(`Stock added for ${result.movements_created} ${result.movements_created === 1 ? 'product' : 'products'}`)
    },
  })
  const canConfirm = included.length > 0 && problems.length === 0 && !confirm.isPending

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle>Check each line</CardTitle>
          <CardDescription>Match every line to one of your products, fix any quantity or cost, and untick lines you do not want to add.</CardDescription>
        </CardHeader>
        <CardContent>
          <ul className="space-y-3" aria-label="Receipt lines">
            {receipt.lines.map((line) => (
              <ReviewLine key={line.id} line={line} decision={decisions[line.id]} reviewable productName={(id) => (id ? productById.get(id)?.name ?? 'Product' : null)} onChange={(patch) => update(line.id, patch)} onPick={() => setPicking(line.id)} />
            ))}
          </ul>
        </CardContent>
      </Card>

      <Card className="mt-4">
        <CardHeader><CardTitle>Before you confirm</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <dl className="grid gap-3 text-sm sm:grid-cols-3">
            <div><dt className="text-muted-foreground">Products to restock</dt><dd className="text-xl font-semibold">{included.length} <span className="text-sm font-normal text-muted-foreground">of {receipt.lines.length} lines</span></dd></div>
            <div><dt className="text-muted-foreground">Total quantity</dt><dd className="tabular text-xl font-semibold">{formatQuantity(String(totalQty))}</dd></div>
            <div><dt className="text-muted-foreground">Total supplier cost</dt><dd className="tabular text-xl font-semibold">{formatKsh(fromCents(totalCents))}</dd></div>
          </dl>
          {included.length > 0 && (
            <ul className="text-sm text-muted-foreground" aria-label="Products that will be restocked">
              {included.map(([id, d]) => <li key={id}>{productById.get(d.productId ?? '')?.name ?? 'Choose a product'} · {formatQuantity(d.quantity)} × {formatKsh(d.unitCost)}{d.updateCost ? ' · updates cost price' : ''}</li>)}
            </ul>
          )}
          {problems.length > 0 && <p className="text-sm text-destructive" role="alert">{problems.length} {problems.length === 1 ? 'line needs' : 'lines need'} a product and a valid quantity and cost.</p>}
          {confirm.isError && <Alert variant="destructive" role="alert">{describeReceiptError(confirm.error)}</Alert>}
          <Button size="lg" className="w-full sm:w-auto" disabled={!canConfirm} onClick={() => setConfirming(true)}><Check aria-hidden="true" /> Add to stock</Button>
          <p className="text-xs text-muted-foreground">This records a restock for each ticked line, exactly like Inventory → Restock. It cannot be undone; use an adjustment to correct a mistake.</p>
        </CardContent>
      </Card>

      <ConfirmDialog open={confirming} onOpenChange={setConfirming} title={`Add ${included.length} ${included.length === 1 ? 'product' : 'products'} to stock?`} description={`Total supplier cost ${formatKsh(fromCents(totalCents))}. Stock and costs will be recorded as restocks from ${receipt.supplier_name ?? 'this receipt'}.`} confirmLabel="Add to stock" onConfirm={async () => { try { await confirm.mutateAsync() } catch { /* shown in the review card once the dialog closes */ } }} />

      <Dialog open={picking !== null} onOpenChange={(o) => !o && setPicking(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Which product is this?</DialogTitle>
            <DialogDescription>{picking ? `Receipt says “${receipt.lines.find((l) => l.id === picking)?.extracted_name ?? ''}”. Pick the matching product that tracks stock.` : ''}</DialogDescription>
          </DialogHeader>
          <ProductPicker trackedOnly autoFocus onPick={(p) => { if (picking) update(picking, { productId: p.id, include: true }); setPicking(null) }} />
          <Link to="/products" className={cn(buttonVariants({ variant: 'ghost' }), 'justify-start')}>Not in your products yet? Add it under Products</Link>
        </DialogContent>
      </Dialog>
    </>
  )
}

/** The image endpoint needs the bearer token, so it is fetched and shown from a blob URL. */
function ReceiptImage({ id }: { id: string }) {
  const [url, setUrl] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    let objectUrl: string | null = null
    let cancelled = false
    void (async () => {
      try {
        const { sessionStore } = await import('@/lib/session')
        const response = await fetch(receiptsApi.imageUrl(id), { headers: { Authorization: `Bearer ${sessionStore.getToken() ?? ''}` }, credentials: 'include' })
        if (!response.ok) throw new Error('image')
        objectUrl = URL.createObjectURL(await response.blob())
        if (!cancelled) setUrl(objectUrl)
      } catch {
        if (!cancelled) setFailed(true)
      }
    })()
    return () => { cancelled = true; if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [id])
  if (failed) return <p className="text-sm text-destructive">The photo could not be loaded.</p>
  if (!url) return <Skeleton className="h-64" />
  return <img src={url} alt="The uploaded supplier receipt" className="h-auto w-full rounded-lg" />
}

function ReviewLine({ line, decision, reviewable, productName, onChange, onPick }: { line: ReceiptLine; decision: Decision | undefined; reviewable: boolean; productName: (id: string | null) => string | null; onChange: (patch: Partial<Decision>) => void; onPick: () => void }) {
  const d = decision
  const match = line.match_status
  const chosen = d ? productName(d.productId) : productName(line.final_product_id ?? line.matched_product_id)
  const badge = match === 'MATCHED' ? <Badge variant="success">Matched</Badge> : match === 'AMBIGUOUS' ? <Badge variant="warning">Which product?</Badge> : <Badge variant="destructive">Not in your products</Badge>
  const lineTotal = d ? lineCents(d.quantity, d.unitCost) : null
  return (
    <li className={cn('rounded-lg border border-border bg-card p-3', d && !d.include && 'opacity-60')}>
      <div className="flex items-start gap-3">
        {reviewable && d && <Checkbox className="mt-1" checked={d.include} aria-label={`Include ${line.extracted_name}`} onChange={(e) => onChange({ include: e.target.checked })} />}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="font-medium">{line.extracted_name}</p>
            {reviewable ? badge : line.review_status === 'APPLIED' ? <Badge variant="success">Restocked</Badge> : line.review_status === 'SKIPPED' ? <Badge variant="neutral">Skipped</Badge> : badge}
            {line.confidence !== null && Number(line.confidence) < 0.6 && <Badge variant="warning"><AlertTriangle className="size-3" aria-hidden="true" /> Hard to read</Badge>}
          </div>
          <p className="text-xs text-muted-foreground">Receipt: {formatQuantity(line.extracted_quantity)} × {formatKsh(line.extracted_unit_cost)}{line.extracted_line_total ? ` = ${formatKsh(line.extracted_line_total)}` : ''}</p>
          {line.warnings.length > 0 && <ul className="mt-1 text-xs text-warning">{line.warnings.map((w) => <li key={w}>{WARNING_TEXT[w] ?? w}</li>)}</ul>}
          {reviewable && d ? (
            <div className="mt-3 grid gap-3 sm:grid-cols-[1fr_auto_auto]">
              <div>
                <span className="mb-1 block text-xs text-muted-foreground">Your product</span>
                <Button type="button" variant={d.productId ? 'outline' : 'default'} className="w-full justify-start" onClick={onPick}>{chosen ?? 'Choose a product'}</Button>
              </div>
              <div>
                <label htmlFor={`qty-${line.id}`} className="mb-1 block text-xs text-muted-foreground">Quantity</label>
                <Input id={`qty-${line.id}`} inputMode="decimal" className="w-full sm:w-24" value={d.quantity} invalid={Number(d.quantity) <= 0 || lineCents(d.quantity, d.unitCost) === null} onChange={(e) => onChange({ quantity: e.target.value })} />
              </div>
              <div>
                <label htmlFor={`cost-${line.id}`} className="mb-1 block text-xs text-muted-foreground">Cost each (KSh)</label>
                <Input id={`cost-${line.id}`} inputMode="decimal" className="w-full sm:w-28" value={d.unitCost} invalid={toCents(d.unitCost) === null} onChange={(e) => onChange({ unitCost: e.target.value })} />
              </div>
              <div className="flex items-center justify-between gap-3 sm:col-span-3">
                <label className="flex items-center gap-2 text-sm"><Checkbox checked={d.updateCost} onChange={(e) => onChange({ updateCost: e.target.checked })} /> Also make this the product's cost price</label>
                <span className="tabular text-sm font-semibold">{lineTotal === null ? '—' : formatKsh(fromCents(lineTotal))}</span>
              </div>
            </div>
          ) : (
            line.final_product_id && <p className="mt-1 text-sm">→ {chosen}: {formatQuantity(line.final_quantity)} × {formatKsh(line.final_unit_cost)}</p>
          )}
        </div>
      </div>
    </li>
  )
}
