import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Archive, ArchiveRestore, ArrowLeft, Pencil } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { buttonVariants } from '@/components/ui/button-variants'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { ErrorState } from '@/components/ui/error-state'
import { PageHeader } from '@/components/ui/page-header'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/features/auth/auth-context'
import { MovementsTable } from '@/features/inventory/MovementsTable'
import { useMovements } from '@/features/inventory/hooks'
import { describeError } from '@/lib/errors'
import { formatKsh, formatQuantity } from '@/lib/money'
import { queryKeys } from '@/lib/query-keys'
import { cn } from '@/lib/utils'

import { productsApi } from './api'
import { useCategories, useProduct } from './hooks'
import { ProductFormDialog } from './ProductFormDialog'
import { StockBadge } from './StockBadge'

export default function ProductDetailPage() {
  const { productId } = useParams()
  const { session } = useAuth()
  const isOwner = session?.role === 'OWNER'
  const queryClient = useQueryClient()
  const product = useProduct(productId)
  const categories = useCategories()
  const movements = useMovements({ product_id: productId, limit: 20 }, !!productId && !!product.data?.track_inventory)
  const [editing, setEditing] = useState(false)
  const [confirmArchive, setConfirmArchive] = useState(false)

  const toggleArchive = useMutation({
    mutationFn: (isActive: boolean) => productsApi.update(productId!, { is_active: isActive }),
    onSuccess: (saved) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.products.all })
      void queryClient.invalidateQueries({ queryKey: queryKeys.inventory.all })
      toast.success(saved.is_active ? 'Product restored' : 'Product archived')
    },
    onError: (error) => toast.error(describeError(error)),
  })

  if (product.isPending) return <div className="space-y-4"><Skeleton className="h-8 w-64" /><Skeleton className="h-40" /></div>
  if (product.isError) return <ErrorState error={product.error} title="Could not load this product" onRetry={() => product.refetch()} />
  const p = product.data
  const category = p.category_id ? categories.data?.find((c) => c.id === p.category_id)?.name : null

  return (
    <>
      <Link to="/products" className="mb-4 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" aria-hidden="true" /> All products</Link>
      <PageHeader
        title={p.name}
        description={[category, p.sku, p.unit].filter(Boolean).join(' · ')}
        actions={
          isOwner ? (
            <>
              <Button variant="outline" onClick={() => setEditing(true)}><Pencil aria-hidden="true" /> Edit</Button>
              {p.is_active ? (
                <Button variant="outline" onClick={() => setConfirmArchive(true)}><Archive aria-hidden="true" /> Archive</Button>
              ) : (
                <Button onClick={() => toggleArchive.mutate(true)} loading={toggleArchive.isPending}><ArchiveRestore aria-hidden="true" /> Restore</Button>
              )}
            </>
          ) : undefined
        }
      />
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardContent className="p-5">
            <p className="text-sm text-muted-foreground">Selling price</p>
            <p className="tabular mt-1 text-2xl font-semibold">{formatKsh(p.selling_price)}</p>
            {isOwner && <p className="mt-1 text-xs text-muted-foreground">{p.cost_price ? `Cost ${formatKsh(p.cost_price)} per ${p.unit}` : 'No cost price yet — profit on this product is not measured'}</p>}
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-5">
            <p className="text-sm text-muted-foreground">Stock</p>
            <p className="tabular mt-1 text-2xl font-semibold">{p.track_inventory ? `${formatQuantity(p.stock_quantity)} ${p.unit}` : '—'}</p>
            <div className="mt-2">{p.is_active ? <StockBadge product={p} /> : <Badge variant="neutral">Archived</Badge>}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-5">
            <p className="text-sm text-muted-foreground">Details</p>
            <dl className="mt-2 space-y-1 text-sm">
              <div className="flex justify-between gap-3"><dt className="text-muted-foreground">Barcode</dt><dd>{p.barcode ?? '—'}</dd></div>
              <div className="flex justify-between gap-3"><dt className="text-muted-foreground">Low-stock alert</dt><dd>{p.track_inventory ? (p.low_stock_threshold ? formatQuantity(p.low_stock_threshold) : 'business default') : '—'}</dd></div>
              <div className="flex justify-between gap-3"><dt className="text-muted-foreground">Stock tracking</dt><dd>{p.track_inventory ? 'On' : 'Off'}</dd></div>
            </dl>
          </CardContent>
        </Card>
      </div>
      {p.track_inventory && (
        <Card className="mt-4">
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle>Stock movements</CardTitle>
            <Link to={`/inventory?product_id=${p.id}`} className={cn(buttonVariants({ variant: 'ghost', size: 'sm' }))}>Full history</Link>
          </CardHeader>
          <CardContent>
            <MovementsTable query={movements} compact />
          </CardContent>
        </Card>
      )}
      <ProductFormDialog open={editing} onOpenChange={setEditing} product={p} />
      <ConfirmDialog
        open={confirmArchive}
        onOpenChange={setConfirmArchive}
        title={`Archive “${p.name}”?`}
        description="It disappears from the sell screen and product list, but every past sale keeps it. You can restore it later."
        confirmLabel="Archive"
        onConfirm={() => toggleArchive.mutateAsync(false).then(() => undefined)}
      />
    </>
  )
}
