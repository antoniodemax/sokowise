import { Plus, UserRound, X } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import type { Customer } from '@/features/customers/api'
import { CustomerFormDialog } from '@/features/customers/CustomerFormDialog'
import { CustomerPicker } from '@/features/customers/CustomerPicker'
import { fromCents } from '@/lib/decimal'
import { formatKsh } from '@/lib/money'

interface CustomerSectionProps {
  customer: Customer | null
  creditCents: number
  onChange: (customer: Customer | null) => void
}

export function CustomerSection({ customer, creditCents, onChange }: CustomerSectionProps) {
  const [picking, setPicking] = useState(false)
  const [creating, setCreating] = useState(false)
  const balance = customer ? Math.round(Number(customer.balance) * 100) : 0
  const limit = customer?.credit_limit === null || customer === null ? null : Math.round(Number(customer.credit_limit) * 100)
  const projected = balance + creditCents
  const overLimit = limit !== null && creditCents > 0 && projected > limit

  return (
    <div>
      {customer ? (
        <div className="flex items-center justify-between gap-3 rounded-lg border border-border bg-card p-3">
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">{customer.name}</p>
            <p className="text-xs text-muted-foreground">
              {balance > 0 ? `Owes ${formatKsh(fromCents(balance))}` : 'Nothing owed'}
              {limit !== null && ` · limit ${limit === 0 ? 'no credit' : formatKsh(fromCents(limit))}`}
              {creditCents > 0 && ` · after this sale ${formatKsh(fromCents(projected))}`}
            </p>
            {overLimit && <p className="mt-1 text-xs text-warning">This goes over their credit limit.</p>}
          </div>
          <Button type="button" variant="ghost" size="icon" aria-label="Remove customer" onClick={() => onChange(null)}><X aria-hidden="true" /></Button>
        </div>
      ) : (
        <Button type="button" variant="outline" className="w-full justify-start" onClick={() => setPicking(true)}><UserRound aria-hidden="true" /> Add customer (needed for credit)</Button>
      )}
      <Dialog open={picking} onOpenChange={setPicking}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Who is buying?</DialogTitle>
            <DialogDescription>Needed for credit sales; optional otherwise.</DialogDescription>
          </DialogHeader>
          <CustomerPicker autoFocus onPick={(c) => { onChange(c); setPicking(false) }} />
          <Button type="button" variant="ghost" className="justify-start" onClick={() => { setPicking(false); setCreating(true) }}><Plus aria-hidden="true" /> New customer</Button>
        </DialogContent>
      </Dialog>
      <CustomerFormDialog open={creating} onOpenChange={setCreating} onSaved={(c) => onChange(c)} />
    </div>
  )
}
