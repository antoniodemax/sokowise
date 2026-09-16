import { Plus, Trash2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { fromCents } from '@/lib/decimal'
import { formatKsh } from '@/lib/money'

import { PAYMENT_LABELS, type PaymentMethod } from './api'
import type { Tender, TenderTotals } from './cart'

interface TenderEditorProps {
  tenders: Tender[]
  totals: TenderTotals
  total: number | null
  hasCustomer: boolean
  onChange: (tenders: Tender[]) => void
}

export function TenderEditor({ tenders, totals, total, hasCustomer, onChange }: TenderEditorProps) {
  const update = (id: string, patch: Partial<Tender>) => onChange(tenders.map((t) => (t.id === id ? { ...t, ...patch, touched: patch.amount !== undefined ? true : t.touched } : t)))
  const remove = (id: string) => onChange(tenders.filter((t) => t.id !== id))
  const add = (method: PaymentMethod) => {
    const remaining = totals.remaining !== null && totals.remaining > 0 ? fromCents(totals.remaining) : ''
    onChange([...tenders, { id: crypto.randomUUID(), method, amount: remaining, reference: '', touched: true }])
  }
  const fillRemaining = (tender: Tender) => {
    if (totals.remaining === null) return
    const own = Number(tender.amount || 0) * 100
    update(tender.id, { amount: fromCents(Math.max(0, Math.round(own) + totals.remaining)) })
  }

  return (
    <div className="space-y-3">
      <ul className="space-y-3" aria-label="How the customer pays">
        {tenders.map((tender, index) => (
          <li key={tender.id} className="rounded-lg border border-border bg-card p-3">
            <div className="grid grid-cols-[1fr_1fr_auto] items-end gap-2">
              <div>
                <label htmlFor={`method-${tender.id}`} className="mb-1 block text-xs text-muted-foreground">Method</label>
                <Select id={`method-${tender.id}`} value={tender.method} onChange={(e) => update(tender.id, { method: e.target.value as PaymentMethod, reference: '' })}>
                  {(Object.keys(PAYMENT_LABELS) as PaymentMethod[]).map((m) => <option key={m} value={m}>{PAYMENT_LABELS[m]}</option>)}
                </Select>
              </div>
              <div>
                <label htmlFor={`amount-${tender.id}`} className="mb-1 block text-xs text-muted-foreground">Amount (KSh)</label>
                <Input id={`amount-${tender.id}`} inputMode="decimal" value={tender.amount} invalid={totals.tendered === null && tender.amount.trim() !== '' && !/^\d+(\.\d{1,2})?$/.test(tender.amount)} onChange={(e) => update(tender.id, { amount: e.target.value })} />
              </div>
              <Button type="button" variant="ghost" size="icon" aria-label={`Remove payment ${index + 1}`} disabled={tenders.length === 1} onClick={() => remove(tender.id)} className="text-muted-foreground hover:text-destructive"><Trash2 aria-hidden="true" /></Button>
            </div>
            {tender.method === 'MPESA' && (
              <div className="mt-2">
                <label htmlFor={`ref-${tender.id}`} className="mb-1 block text-xs text-muted-foreground">M-Pesa code <span className="text-muted-foreground/80">(typed in for your records — not verified with Safaricom)</span></label>
                <Input id={`ref-${tender.id}`} value={tender.reference} maxLength={64} placeholder="e.g. QGH7X2K9LM" onChange={(e) => update(tender.id, { reference: e.target.value.toUpperCase() })} />
              </div>
            )}
            {tender.method === 'CREDIT' && (
              <p className={`mt-2 text-xs ${hasCustomer ? 'text-muted-foreground' : 'text-destructive'}`}>
                {hasCustomer ? 'This amount is added to what the customer owes you.' : 'Pick a customer above to sell on credit.'}
              </p>
            )}
            {totals.remaining !== null && totals.remaining !== 0 && (
              <button type="button" className="mt-2 text-xs font-medium text-primary hover:underline" onClick={() => fillRemaining(tender)}>Fill remaining {formatKsh(fromCents(Math.abs(totals.remaining)))}</button>
            )}
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap gap-2">
        {(Object.keys(PAYMENT_LABELS) as PaymentMethod[]).map((m) => (
          <Button key={m} type="button" variant="outline" onClick={() => add(m)}><Plus aria-hidden="true" /> {PAYMENT_LABELS[m]}</Button>
        ))}
      </div>
      <div className="flex items-center justify-between rounded-lg bg-muted px-3 py-2 text-sm" aria-live="polite">
        <span className="text-muted-foreground">{totals.remaining === null || total === null ? 'Check the amounts' : totals.remaining > 0 ? 'Still to pay' : totals.remaining < 0 ? 'Over by' : 'Fully paid'}</span>
        <span className={`tabular font-semibold ${totals.remaining === 0 ? 'text-success' : totals.remaining !== null && totals.remaining !== 0 ? 'text-warning' : ''}`}>
          {totals.remaining === null ? '—' : formatKsh(fromCents(Math.abs(totals.remaining)))}
        </span>
      </div>
    </div>
  )
}
