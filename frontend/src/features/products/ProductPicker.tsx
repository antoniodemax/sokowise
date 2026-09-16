import { Package, Search } from 'lucide-react'
import { useId, useState } from 'react'

import { Input } from '@/components/ui/input'
import { formatKsh, formatQuantity } from '@/lib/money'
import { useDebouncedValue } from '@/lib/use-debounce'
import { cn } from '@/lib/utils'

import type { Product } from './api'
import { useProducts } from './hooks'

interface ProductPickerProps {
  onPick: (product: Product) => void
  /** Only products that track stock (for restock/adjust). */
  trackedOnly?: boolean
  autoFocus?: boolean
  placeholder?: string
  /** Keep the list open even without a query (small catalogues). */
  showAll?: boolean
}

/** Search-as-you-type over the business's active products; a listbox of the top matches. */
export function ProductPicker({ onPick, trackedOnly, autoFocus, placeholder = 'Search products by name, SKU or barcode', showAll = true }: ProductPickerProps) {
  const [query, setQuery] = useState('')
  const debounced = useDebouncedValue(query.trim())
  const listId = useId()
  const products = useProducts({ q: debounced || undefined, limit: 20 }, showAll || debounced.length > 0)
  const rows = (products.data ?? []).filter((p) => !trackedOnly || p.track_inventory)

  return (
    <div className="space-y-2">
      <div className="relative">
        <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
        <Input
          role="combobox"
          aria-expanded={rows.length > 0}
          aria-controls={listId}
          aria-label="Search products"
          className="pl-9"
          placeholder={placeholder}
          value={query}
          autoFocus={autoFocus}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
      <ul id={listId} role="listbox" aria-label="Matching products" className="max-h-64 divide-y divide-border overflow-y-auto rounded-lg border border-border bg-card">
        {products.isPending && (showAll || debounced) ? (
          <li className="px-3 py-3 text-sm text-muted-foreground">Searching…</li>
        ) : rows.length === 0 ? (
          <li className="flex items-center gap-2 px-3 py-3 text-sm text-muted-foreground">
            <Package className="size-4" aria-hidden="true" /> {debounced ? `No products match “${debounced}”` : trackedOnly ? 'No products track stock yet' : 'No products yet'}
          </li>
        ) : (
          rows.map((product) => (
            <li key={product.id} role="option" aria-selected={false}>
              <button type="button" onClick={() => { onPick(product); setQuery('') }} className={cn('flex min-h-12 w-full items-center justify-between gap-3 px-3 py-2 text-left hover:bg-muted focus-visible:bg-muted')}>
                <span className="min-w-0">
                  <span className="block truncate text-sm font-medium">{product.name}</span>
                  <span className="block text-xs text-muted-foreground">
                    {product.sku ? `${product.sku} · ` : ''}
                    {product.track_inventory ? `${formatQuantity(product.stock_quantity)} ${product.unit} in stock` : 'Not stock-tracked'}
                  </span>
                </span>
                <span className="tabular shrink-0 text-sm font-semibold">{formatKsh(product.selling_price)}</span>
              </button>
            </li>
          ))
        )}
      </ul>
    </div>
  )
}
