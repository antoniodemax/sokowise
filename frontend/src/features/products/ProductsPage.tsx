import { Package, Plus, Search, Tags } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { EmptyState } from '@/components/ui/empty-state'
import { ErrorState } from '@/components/ui/error-state'
import { Input } from '@/components/ui/input'
import { PageHeader } from '@/components/ui/page-header'
import { Select } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useAuth } from '@/features/auth/auth-context'
import { formatKsh, formatQuantity } from '@/lib/money'
import { useDebouncedValue } from '@/lib/use-debounce'

import { CategoriesDialog } from './CategoriesDialog'
import { useCategories, useProducts } from './hooks'
import { ProductFormDialog } from './ProductFormDialog'
import { StockBadge } from './StockBadge'

export default function ProductsPage() {
  const { session } = useAuth()
  const navigate = useNavigate()
  const isOwner = session?.role === 'OWNER'
  const [query, setQuery] = useState('')
  const [categoryId, setCategoryId] = useState('')
  const [includeArchived, setIncludeArchived] = useState(false)
  const [creating, setCreating] = useState(false)
  const [managingCategories, setManagingCategories] = useState(false)
  const debounced = useDebouncedValue(query.trim())
  const params = { q: debounced || undefined, category_id: categoryId || undefined, include_archived: includeArchived || undefined, limit: 200 }
  const products = useProducts(params)
  const categories = useCategories()
  const categoryName = new Map((categories.data ?? []).map((c) => [c.id, c.name]))

  return (
    <>
      <PageHeader
        title="Products"
        description={isOwner ? 'What you sell, with prices and stock.' : 'Prices and stock for everything the shop sells.'}
        actions={
          isOwner ? (
            <>
              <Button variant="outline" onClick={() => setManagingCategories(true)}><Tags aria-hidden="true" /> Categories</Button>
              <Button onClick={() => setCreating(true)}><Plus aria-hidden="true" /> Add product</Button>
            </>
          ) : undefined
        }
      />
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
          <Input aria-label="Search products" placeholder="Search by name, SKU or barcode" className="pl-9" value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>
        <div className="w-full sm:w-56">
          <Select aria-label="Filter by category" value={categoryId} onChange={(e) => setCategoryId(e.target.value)}>
            <option value="">All categories</option>
            {(categories.data ?? []).map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </Select>
        </div>
        <label className="flex min-h-11 items-center gap-2 text-sm">
          <Checkbox checked={includeArchived} onChange={(e) => setIncludeArchived(e.target.checked)} /> Show archived
        </label>
      </div>

      {products.isPending ? (
        <div className="space-y-2" aria-busy="true" aria-label="Loading products">
          {Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="h-12" />)}
        </div>
      ) : products.isError ? (
        <ErrorState error={products.error} title="Could not load products" onRetry={() => products.refetch()} />
      ) : products.data.length === 0 ? (
        <EmptyState
          icon={Package}
          title={debounced || categoryId ? 'No products match' : 'No products yet'}
          description={debounced || categoryId ? 'Try a different search or category.' : isOwner ? 'Add the things you sell — a name and a price is enough to start.' : 'The owner has not added products yet.'}
          action={isOwner && !debounced && !categoryId ? <Button onClick={() => setCreating(true)}><Plus aria-hidden="true" /> Add your first product</Button> : undefined}
        />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Product</TableHead>
              <TableHead className="text-right">Price</TableHead>
              {isOwner && <TableHead className="hidden text-right md:table-cell">Cost</TableHead>}
              <TableHead className="text-right">Stock</TableHead>
              <TableHead className="hidden sm:table-cell">Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {products.data.map((product) => (
              <TableRow key={product.id} className="cursor-pointer" onClick={() => navigate(`/products/${product.id}`)}>
                <TableCell>
                  <button type="button" className="block w-full text-left font-medium hover:underline" onClick={(e) => { e.stopPropagation(); navigate(`/products/${product.id}`) }}>
                    {product.name}
                  </button>
                  <span className="block text-xs text-muted-foreground">
                    {[product.sku, product.category_id ? categoryName.get(product.category_id) : null].filter(Boolean).join(' · ') || product.unit}
                    {!product.is_active && ' · archived'}
                  </span>
                </TableCell>
                <TableCell className="tabular text-right">{formatKsh(product.selling_price)}</TableCell>
                {isOwner && <TableCell className="tabular hidden text-right text-muted-foreground md:table-cell">{product.cost_price ? formatKsh(product.cost_price) : '—'}</TableCell>}
                <TableCell className="tabular text-right">{product.track_inventory ? `${formatQuantity(product.stock_quantity)} ${product.unit}` : '—'}</TableCell>
                <TableCell className="hidden sm:table-cell">{product.is_active ? <StockBadge product={product} /> : <Badge variant="neutral">Archived</Badge>}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      <ProductFormDialog open={creating} onOpenChange={setCreating} onSaved={(p) => navigate(`/products/${p.id}`)} />
      <CategoriesDialog open={managingCategories} onOpenChange={setManagingCategories} />
    </>
  )
}
