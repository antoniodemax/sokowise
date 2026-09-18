import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Plus } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'

import { Alert } from '@/components/ui/alert'
import { BackLink } from '@/components/ui/back-link'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { ErrorState } from '@/components/ui/error-state'
import { Input } from '@/components/ui/input'
import { PageHeader } from '@/components/ui/page-header'
import { Skeleton } from '@/components/ui/skeleton'
import { describeError } from '@/lib/errors'
import { queryKeys } from '@/lib/query-keys'
import { cn } from '@/lib/utils'

import { productsApi, type ProductCreate, type StarterItem } from './api'

interface Row extends StarterItem {
  ticked: boolean
  price: string
  stock: string
}

const MONEY = /^\d+(\.\d{1,2})?$/
const QTY = /^\d+(\.\d{1,3})?$/

/**
 * First-run setup: tick what the shop sells from a curated list, adjust prices, add them
 * all at once. The owner can skip; nothing here is required to use the app.
 */
export default function SetupPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const starter = useQuery({ queryKey: ['products', 'starter'] as const, queryFn: ({ signal }) => productsApi.starter(signal) })
  const [rows, setRows] = useState<Row[] | null>(null)
  const list = rows ?? starter.data?.map((item) => ({ ...item, ticked: item.name === 'Other', price: item.selling_price, stock: '' })) ?? null
  const ticked = list?.filter((r) => r.ticked) ?? []
  const invalid = ticked.filter((r) => !MONEY.test(r.price.trim()) || (r.stock.trim() !== '' && !(QTY.test(r.stock.trim()) && Number(r.stock) > 0)))

  const update = (index: number, patch: Partial<Row>) => setRows((current) => (current ?? list ?? []).map((r, i) => (i === index ? { ...r, ...patch } : r)))

  const add = useMutation({
    mutationFn: () => {
      const items: ProductCreate[] = ticked.map((r) => ({
        name: r.name,
        selling_price: r.price.trim(),
        cost_price: r.cost_price,
        unit: r.unit,
        track_inventory: r.track_inventory,
        ...(r.track_inventory && r.stock.trim() !== '' ? { opening_stock: r.stock.trim() } : {}),
      }))
      return productsApi.createBulk(items)
    },
    onSuccess: (created) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.products.all })
      toast.success(`${created.length} ${created.length === 1 ? 'item' : 'items'} added. You can sell now.`)
      navigate('/dashboard')
    },
  })

  return (
    <>
      <BackLink to="/dashboard">Dashboard</BackLink>
      <PageHeader title="What do you sell?" description="Tick the items you sell and fix the prices. You can change anything later, and add more as you go." />
      {starter.isPending ? (
        <div className="space-y-2" aria-busy="true"><Skeleton className="h-12" /><Skeleton className="h-12" /><Skeleton className="h-12" /></div>
      ) : starter.isError ? (
        <ErrorState error={starter.error} title="Could not load the starter list" onRetry={() => starter.refetch()} />
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>Common items for your kind of shop</CardTitle>
            <CardDescription>Prices are a starting point. Tap an item to tick it, type your own price, and how many you have in the shop now (leave empty if you don't count it yet).</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <ul className="divide-y divide-border rounded-lg border border-border">
              {(list ?? []).map((row, index) => (
                <li key={row.name} className={cn('grid grid-cols-[auto_1fr] items-center gap-x-3 gap-y-2 px-3 py-2 sm:flex', row.ticked && 'bg-primary-soft/40')}>
                  <button
                    type="button"
                    role="checkbox"
                    aria-checked={row.ticked}
                    aria-label={`Sell ${row.name}`}
                    onClick={() => update(index, { ticked: !row.ticked })}
                    className={cn('flex size-10 shrink-0 items-center justify-center rounded-md border', row.ticked ? 'border-primary bg-primary text-primary-foreground' : 'border-border bg-background')}
                  >
                    {row.ticked && <Check className="size-5" aria-hidden="true" />}
                  </button>
                  <span className="min-w-0 sm:flex-1">
                    <span className="block font-medium">{row.name}</span>
                    <span className="block text-xs text-muted-foreground">{row.track_inventory ? 'Stock counted' : 'Not counted'}{row.cost_price ? ` · cost KSh ${row.cost_price}` : ''}</span>
                  </span>
                  <div className="col-start-2 flex items-center gap-3 sm:col-auto">
                    <label className="flex items-center gap-1 text-sm">
                      <span className="text-muted-foreground">KSh</span>
                      <Input aria-label={`Price of ${row.name}`} inputMode="decimal" value={row.price} invalid={row.ticked && !MONEY.test(row.price.trim())} onChange={(e) => update(index, { price: e.target.value, ticked: true })} className="w-20" />
                    </label>
                    {row.track_inventory && (
                      <label className="flex items-center gap-1 text-sm">
                        <span className="text-muted-foreground">Have</span>
                        <Input aria-label={`Stock of ${row.name}`} inputMode="decimal" placeholder="0" value={row.stock} invalid={row.ticked && row.stock.trim() !== '' && !(QTY.test(row.stock.trim()) && Number(row.stock) > 0)} onChange={(e) => update(index, { stock: e.target.value, ticked: true })} className="w-16" />
                      </label>
                    )}
                  </div>
                </li>
              ))}
            </ul>
            {add.isError && <Alert variant="destructive" role="alert">{describeError(add.error)}</Alert>}
            {invalid.length > 0 && <Alert variant="warning" role="alert">Check the price or stock of {invalid.map((r) => r.name).join(', ')} to continue.</Alert>}
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-sm text-muted-foreground">{ticked.length} ticked</p>
              <div className="flex gap-2">
                <Button variant="outline" onClick={() => navigate('/dashboard')}>Skip for now</Button>
                <Button onClick={() => add.mutate()} loading={add.isPending} disabled={ticked.length === 0 || invalid.length > 0}><Plus aria-hidden="true" /> Add {ticked.length} {ticked.length === 1 ? 'item' : 'items'}</Button>
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </>
  )
}
