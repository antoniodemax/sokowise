import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Check, X } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { toast } from 'sonner'

import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { describeError } from '@/lib/errors'
import { formatKsh } from '@/lib/money'
import { queryKeys } from '@/lib/query-keys'

import { assistantApi, type Proposal, type ProposalResult } from './api'

const KIND_TITLE: Record<Proposal['kind'], string> = {
  product: 'New product',
  sale: 'Sale',
  repayment: 'Deni payment',
  restock: 'Restock',
}

const APPLIED_TEXT: Record<Proposal['kind'], string> = {
  product: 'Product added',
  sale: 'Sale recorded',
  repayment: 'Deni payment recorded',
  restock: 'Stock added',
}

/** Editable fields per kind: label, key, and whether it is money. Everything else is passed through untouched. */
const FIELDS: Record<Proposal['kind'], { key: string; label: string; money?: boolean }[]> = {
  product: [
    { key: 'name', label: 'Name' },
    { key: 'selling_price', label: 'Selling price (KSh)', money: true },
    { key: 'cost_price', label: 'Cost price (KSh)', money: true },
    { key: 'opening_stock', label: 'Stock now' },
  ],
  sale: [],
  repayment: [
    { key: 'amount', label: 'Amount (KSh)', money: true },
    { key: 'reference', label: 'M-Pesa code' },
  ],
  restock: [
    { key: 'quantity', label: 'Quantity' },
    { key: 'unit_cost', label: 'Cost per unit (KSh)', money: true },
    { key: 'supplier_name', label: 'Supplier' },
  ],
}

function entityLink(kind: Proposal['kind'], id: string, payload: Record<string, unknown>): string | null {
  if (kind === 'product') return `/products/${id}`
  if (kind === 'sale') return `/sales/${id}`
  if (kind === 'repayment' && typeof payload.customer_id === 'string') return `/customers/${payload.customer_id}`
  if (kind === 'restock' && typeof payload.product_id === 'string') return `/products/${payload.product_id}`
  return null
}

export function ProposalCard({ conversationId, messageId, proposal, onResult }: { conversationId: string; messageId: string; proposal: Proposal; onResult: (result: ProposalResult) => void }) {
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState<Record<string, unknown>>(proposal.payload)
  const [error, setError] = useState<string | null>(null)
  const settle = (result: ProposalResult) => {
    for (const k of [queryKeys.products.all, queryKeys.sales.all, queryKeys.inventory.all, queryKeys.customers.all, queryKeys.analytics.all]) void queryClient.invalidateQueries({ queryKey: k })
    onResult(result)
  }
  const confirm = useMutation({
    mutationFn: () => assistantApi.confirmProposal(conversationId, messageId, draft),
    onSuccess: (result) => { setError(null); toast.success(APPLIED_TEXT[proposal.kind]); settle(result) },
    onError: (e) => setError(describeError(e)),
  })
  const reject = useMutation({
    mutationFn: () => assistantApi.rejectProposal(conversationId, messageId),
    onSuccess: (result) => { setError(null); settle(result) },
    onError: (e) => setError(describeError(e)),
  })

  const title = KIND_TITLE[proposal.kind]
  if (proposal.status !== 'PENDING') {
    const link = proposal.entity_id ? entityLink(proposal.kind, proposal.entity_id, proposal.payload) : null
    return (
      <div className="mt-3 rounded-lg border border-border bg-muted/40 px-3 py-2 text-sm" data-testid="proposal-card">
        <span className="font-medium">{proposal.status === 'APPLIED' ? APPLIED_TEXT[proposal.kind] : proposal.status === 'REJECTED' ? 'Not recorded' : 'Expired'}</span>
        {link && proposal.status === 'APPLIED' && <Link to={link} className="ml-2 font-medium text-primary hover:underline">View</Link>}
      </div>
    )
  }

  const lines = Array.isArray(draft.lines) ? (draft.lines as { quantity: string; unit_price: string | null; product_id: string }[]) : []
  const payments = Array.isArray(draft.payments) ? (draft.payments as { method: string; amount: string }[]) : []
  return (
    <div className="mt-3 rounded-lg border border-primary/40 bg-primary-soft/30 p-3 text-sm" role="group" aria-label={`${title} to confirm`} data-testid="proposal-card">
      <p className="font-medium">{title} · check and confirm</p>
      {proposal.kind === 'sale' && (
        <ul className="mt-2 space-y-1 text-muted-foreground">
          {lines.map((l, i) => <li key={i}>{l.quantity} × {l.unit_price ? formatKsh(l.unit_price) : 'shop price'}</li>)}
          <li className="font-medium text-foreground">Paid: {payments.map((p) => `${p.method === 'MPESA' ? 'M-Pesa' : p.method === 'CASH' ? 'Cash' : 'Deni'} ${formatKsh(p.amount)}`).join(' + ')}</li>
        </ul>
      )}
      {FIELDS[proposal.kind].length > 0 && (
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          {FIELDS[proposal.kind].map((f) => (
            <label key={f.key} className="grid gap-1 text-xs">
              <span className="text-muted-foreground">{f.label}</span>
              <Input aria-label={f.label} inputMode={f.money || f.key === 'quantity' || f.key === 'opening_stock' ? 'decimal' : undefined} value={draft[f.key] === null || draft[f.key] === undefined ? '' : String(draft[f.key])} onChange={(e) => setDraft((d) => ({ ...d, [f.key]: e.target.value === '' ? null : e.target.value }))} />
            </label>
          ))}
        </div>
      )}
      {error && <Alert variant="destructive" role="alert" className="mt-2">{error}</Alert>}
      <div className="mt-3 flex gap-2">
        <Button size="sm" onClick={() => confirm.mutate()} loading={confirm.isPending} disabled={reject.isPending}><Check aria-hidden="true" /> Confirm</Button>
        <Button size="sm" variant="outline" onClick={() => reject.mutate()} loading={reject.isPending} disabled={confirm.isPending}><X aria-hidden="true" /> Not now</Button>
      </div>
    </div>
  )
}
