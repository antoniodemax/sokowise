import { Search, UserRound } from 'lucide-react'
import { useId, useState } from 'react'

import { Input } from '@/components/ui/input'
import { formatKsh } from '@/lib/money'
import { useDebouncedValue } from '@/lib/use-debounce'

import type { Customer } from './api'
import { useCustomers } from './hooks'

/** Search customers by name or phone and pick one. */
export function CustomerPicker({ onPick, autoFocus }: { onPick: (customer: Customer) => void; autoFocus?: boolean }) {
  const [query, setQuery] = useState('')
  const debounced = useDebouncedValue(query.trim())
  const listId = useId()
  const customers = useCustomers({ q: debounced || undefined, limit: 20 })
  return (
    <div className="space-y-2">
      <div className="relative">
        <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
        <Input role="combobox" aria-controls={listId} aria-expanded aria-label="Search customers" className="pl-9" placeholder="Name or phone" value={query} autoFocus={autoFocus} onChange={(e) => setQuery(e.target.value)} />
      </div>
      <ul id={listId} role="listbox" aria-label="Matching customers" className="max-h-56 divide-y divide-border overflow-y-auto rounded-lg border border-border bg-card">
        {customers.isPending ? (
          <li className="px-3 py-3 text-sm text-muted-foreground">Searching…</li>
        ) : (customers.data ?? []).length === 0 ? (
          <li className="flex items-center gap-2 px-3 py-3 text-sm text-muted-foreground"><UserRound className="size-4" aria-hidden="true" /> {debounced ? 'No customers match' : 'No customers yet'}</li>
        ) : (
          customers.data!.map((customer) => (
            <li key={customer.id} role="option" aria-selected={false}>
              <button type="button" onClick={() => onPick(customer)} className="flex min-h-12 w-full items-center justify-between gap-3 px-3 py-2 text-left hover:bg-muted focus-visible:bg-muted">
                <span className="min-w-0">
                  <span className="block truncate text-sm font-medium">{customer.name}</span>
                  <span className="block text-xs text-muted-foreground">{customer.phone ?? 'No phone'}</span>
                </span>
                <span className={`tabular shrink-0 text-xs ${Number(customer.balance) > 0 ? 'text-warning' : 'text-muted-foreground'}`}>
                  {Number(customer.balance) > 0 ? `owes ${formatKsh(customer.balance)}` : 'no debt'}
                </span>
              </button>
            </li>
          ))
        )}
      </ul>
    </div>
  )
}
