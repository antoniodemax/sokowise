import { AlertTriangle, ClipboardList, PackagePlus, ScanLine, SlidersHorizontal } from 'lucide-react'
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router'

import { Button } from '@/components/ui/button'
import { buttonVariants } from '@/components/ui/button-variants'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { ErrorState } from '@/components/ui/error-state'
import { PageHeader } from '@/components/ui/page-header'
import { Select } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useAuth } from '@/features/auth/auth-context'
import { useProducts } from '@/features/products/hooks'
import { formatQuantity } from '@/lib/money'

import { MOVEMENT_LABELS, type MovementType } from './api'
import { useLowStock, useMovements } from './hooks'
import { MovementsTable } from './MovementsTable'
import { AdjustDialog, InitialStockDialog, RestockDialog } from './StockDialogs'

const TYPES = Object.keys(MOVEMENT_LABELS) as MovementType[]

export default function InventoryPage() {
  const { session } = useAuth()
  const isOwner = session?.role === 'OWNER'
  const [params, setParams] = useSearchParams()
  const productId = params.get('product_id') ?? ''
  const type = (params.get('type') ?? '') as MovementType | ''
  const [dialog, setDialog] = useState<'restock' | 'adjust' | 'initial' | null>(null)
  const lowStock = useLowStock()
  const products = useProducts({ include_archived: true, limit: 500 })
  const movements = useMovements({ product_id: productId || undefined, movement_type: type || undefined, limit: 100 })
  const names = new Map((products.data ?? []).map((p) => [p.id, p.name]))

  function setFilter(key: string, value: string) {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    setParams(next, { replace: true })
  }

  return (
    <>
      <PageHeader
        title="Inventory"
        description="What is running low and every stock movement."
        actions={
          <>
            {isOwner && <Link to="/inventory/receipts" className={buttonVariants({ variant: 'outline' })}><ScanLine aria-hidden="true" /> Scan receipt</Link>}
            <Button onClick={() => setDialog('restock')}><PackagePlus aria-hidden="true" /> Restock</Button>
            {isOwner && <Button variant="outline" onClick={() => setDialog('adjust')}><SlidersHorizontal aria-hidden="true" /> Adjust</Button>}
            {isOwner && <Button variant="outline" onClick={() => setDialog('initial')}><ClipboardList aria-hidden="true" /> Opening stock</Button>}
          </>
        }
      />
      <Card className="mb-6">
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><AlertTriangle className="size-4 text-warning" aria-hidden="true" /> Running low</CardTitle>
          <CardDescription>Tracked products at or below their low-stock level.</CardDescription>
        </CardHeader>
        <CardContent>
          {lowStock.isPending ? (
            <Skeleton className="h-16" />
          ) : lowStock.isError ? (
            <ErrorState error={lowStock.error} title="Could not check stock levels" onRetry={() => lowStock.refetch()} />
          ) : lowStock.data.length === 0 ? (
            <p className="text-sm text-muted-foreground">Nothing is running low.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Product</TableHead>
                  <TableHead className="text-right">On hand</TableHead>
                  <TableHead className="text-right">Alert level</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {lowStock.data.map((row) => (
                  <TableRow key={row.product_id}>
                    <TableCell className="font-medium">{row.name}{row.sku && <span className="ml-2 text-xs text-muted-foreground">{row.sku}</span>}</TableCell>
                    <TableCell className={`tabular text-right font-semibold ${Number(row.stock_quantity) <= 0 ? 'text-destructive' : 'text-warning'}`}>{formatQuantity(row.stock_quantity)} {row.unit}</TableCell>
                    <TableCell className="tabular text-right text-muted-foreground">{formatQuantity(row.threshold)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Stock movements</CardTitle>
          <CardDescription>Newest first. The "after" column is the stock right after each movement was recorded.</CardDescription>
          <div className="mt-3 grid gap-2 sm:grid-cols-2 md:max-w-lg">
            <Select aria-label="Filter by product" value={productId} onChange={(e) => setFilter('product_id', e.target.value)}>
              <option value="">All products</option>
              {(products.data ?? []).filter((p) => p.track_inventory).map((p) => (
                <option key={p.id} value={p.id}>{p.name}{p.is_active ? '' : ' (archived)'}</option>
              ))}
            </Select>
            <Select aria-label="Filter by movement type" value={type} onChange={(e) => setFilter('type', e.target.value)}>
              <option value="">All movements</option>
              {TYPES.map((t) => (
                <option key={t} value={t}>{MOVEMENT_LABELS[t]}</option>
              ))}
            </Select>
          </div>
        </CardHeader>
        <CardContent>
          <MovementsTable query={movements} productNames={productId ? undefined : names} />
        </CardContent>
      </Card>

      <RestockDialog open={dialog === 'restock'} onOpenChange={(o) => !o && setDialog(null)} />
      <AdjustDialog open={dialog === 'adjust'} onOpenChange={(o) => !o && setDialog(null)} />
      <InitialStockDialog open={dialog === 'initial'} onOpenChange={(o) => !o && setDialog(null)} />
    </>
  )
}
