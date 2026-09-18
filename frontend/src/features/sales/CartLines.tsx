import { Minus, Plus, Trash2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { fromCents, lineCents } from '@/lib/decimal'
import { formatKsh, formatQuantity } from '@/lib/money'
import { cn } from '@/lib/utils'

import type { CartLine } from './cart'

interface CartLinesProps {
  lines: CartLine[]
  invalidLine: number | null
  onChange: (index: number, patch: Partial<Pick<CartLine, 'quantity' | 'unit_price'>>) => void
  onRemove: (index: number) => void
}

function step(quantity: string, delta: number): string {
  const current = Number(quantity) || 0
  const next = Math.max(0, current + delta)
  return Number.isInteger(next) ? String(next) : next.toFixed(3).replace(/0+$/, '').replace(/\.$/, '')
}

export function CartLines({ lines, invalidLine, onChange, onRemove }: CartLinesProps) {
  if (lines.length === 0) {
    return <p className="rounded-lg border border-dashed border-border bg-muted/30 px-4 py-6 text-center text-sm text-muted-foreground">Search for a product above to start the sale.</p>
  }
  return (
    <ul className="divide-y divide-border rounded-lg border border-border bg-card" aria-label="Items in this sale">
      {lines.map((line, index) => {
        const cents = lineCents(line.quantity, line.unit_price)
        const invalid = invalidLine === index
        const whole = line.product.unit === 'piece' || line.product.unit === 'pack' || line.product.unit === 'service'
        const priceChanged = line.unit_price !== line.product.selling_price
        const stockShort = line.product.track_inventory && Number(line.quantity) > Number(line.product.stock_quantity)
        return (
          <li key={line.product.id} className="space-y-2 p-3">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">{line.product.name}</p>
                <p className="text-xs text-muted-foreground">
                  {formatKsh(line.product.selling_price)} / {line.product.unit}
                  {line.product.track_inventory && ` · ${formatQuantity(line.product.stock_quantity)} in stock`}
                </p>
              </div>
              <span className="tabular shrink-0 text-base font-semibold">{cents === null ? '—' : formatKsh(fromCents(cents))}</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="flex items-center" role="group" aria-label={`Quantity of ${line.product.name}`}>
                <Button type="button" variant="outline" size="icon" aria-label={`Less ${line.product.name}`} onClick={() => onChange(index, { quantity: step(line.quantity, -1) })} className="rounded-r-none"><Minus aria-hidden="true" /></Button>
                <Input id={`qty-${line.product.id}`} aria-label={`Quantity of ${line.product.name}`} inputMode={whole ? 'numeric' : 'decimal'} value={line.quantity} invalid={invalid} onChange={(e) => onChange(index, { quantity: e.target.value })} className="tabular w-12 rounded-none border-x-0 px-1 text-center font-medium" aria-describedby={stockShort ? `stock-${line.product.id}` : undefined} />
                <Button type="button" variant="outline" size="icon" aria-label={`More ${line.product.name}`} onClick={() => onChange(index, { quantity: step(line.quantity, 1) })} className="rounded-l-none"><Plus aria-hidden="true" /></Button>
              </div>
              <Input id={`price-${line.product.id}`} aria-label={`Price each for ${line.product.name}`} inputMode="decimal" value={line.unit_price} invalid={invalid} onChange={(e) => onChange(index, { unit_price: e.target.value })} className={cn('tabular ml-auto w-24 text-right', priceChanged && 'border-warning')} />
              <Button type="button" variant="ghost" size="icon" className="size-10 shrink-0 text-muted-foreground hover:bg-destructive-soft hover:text-destructive" aria-label={`Remove ${line.product.name}`} onClick={() => onRemove(index)}><Trash2 aria-hidden="true" /></Button>
            </div>
            {priceChanged && <p className="text-xs text-warning">Price for this sale changed from {formatKsh(line.product.selling_price)} each.</p>}
            {stockShort && <p id={`stock-${line.product.id}`} className="text-xs text-warning">Only {formatQuantity(line.product.stock_quantity)} in stock — the sale will be refused unless stock is updated.</p>}
            {invalid && <p className="text-xs text-destructive" role="alert">Enter a quantity above zero and a price like 150 or 150.50.</p>}
          </li>
        )
      })}
    </ul>
  )
}
