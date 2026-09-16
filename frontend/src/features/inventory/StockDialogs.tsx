import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'

import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import type { Product } from '@/features/products/api'
import { ProductPicker } from '@/features/products/ProductPicker'
import { formatKsh, formatQuantity } from '@/lib/money'
import { queryKeys } from '@/lib/query-keys'

import { stockErrorMessage } from './errors'
import { inventoryApi } from './api'

const quantity = z.string().trim().regex(/^\d+(\.\d{1,3})?$/, 'Enter a quantity like 10 or 2.5').refine((v) => Number(v) > 0, 'Quantity must be more than zero')
const money = z.string().trim().regex(/^\d+(\.\d{1,2})?$/, 'Enter an amount like 150 or 150.50')

function useInvalidateStock() {
  const queryClient = useQueryClient()
  return () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.inventory.all })
    void queryClient.invalidateQueries({ queryKey: queryKeys.products.all })
  }
}

function PickedProduct({ product, onChange }: { product: Product; onChange: () => void }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border border-border bg-muted/40 px-3 py-2">
      <div className="min-w-0">
        <p className="truncate text-sm font-medium">{product.name}</p>
        <p className="text-xs text-muted-foreground">{formatQuantity(product.stock_quantity)} {product.unit} on hand{product.cost_price ? ` · cost ${formatKsh(product.cost_price)}` : ''}</p>
      </div>
      <Button type="button" variant="ghost" size="sm" onClick={onChange}>Change</Button>
    </div>
  )
}

interface StockDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Preselected product (from a product page); otherwise the user picks one. */
  product?: Product
}

// --- Restock --------------------------------------------------------------------

const restockSchema = z.object({
  quantity,
  unit_cost: money,
  supplier_name: z.string().trim().max(120),
  reason: z.string().trim().max(255),
  update_cost_price: z.boolean(),
})
type RestockValues = z.infer<typeof restockSchema>

export function RestockDialog({ open, onOpenChange, product: preset }: StockDialogProps) {
  const [product, setProduct] = useState<Product | undefined>(preset)
  const [serverError, setServerError] = useState<string | null>(null)
  const invalidate = useInvalidateStock()
  const form = useForm<RestockValues>({ resolver: zodResolver(restockSchema), defaultValues: { quantity: '', unit_cost: preset?.cost_price ?? '', supplier_name: '', reason: '', update_cost_price: false } })
  const mutation = useMutation({
    mutationFn: (values: RestockValues) =>
      inventoryApi.restock({ product_id: product!.id, quantity: values.quantity, unit_cost: values.unit_cost, supplier_name: values.supplier_name || null, reason: values.reason || null, update_cost_price: values.update_cost_price }),
    onSuccess: (movement) => {
      invalidate()
      toast.success(`Stock is now ${formatQuantity(movement.quantity_after)} ${product?.unit ?? ''}`.trim())
      onOpenChange(false)
    },
    onError: (error) => setServerError(stockErrorMessage(error)),
  })
  function reset() { setProduct(preset); setServerError(null); form.reset({ quantity: '', unit_cost: preset?.cost_price ?? '', supplier_name: '', reason: '', update_cost_price: false }) }
  const errors = form.formState.errors
  return (
    <Dialog open={open} onOpenChange={(o) => { onOpenChange(o); if (!o) reset() }}>
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Restock</DialogTitle>
          <DialogDescription>Stock you bought or received. This is stock in, not an expense.</DialogDescription>
        </DialogHeader>
        {!product ? (
          <ProductPicker trackedOnly autoFocus onPick={(p) => { setProduct(p); form.setValue('unit_cost', p.cost_price ?? '') }} />
        ) : (
          <form onSubmit={form.handleSubmit((v) => { setServerError(null); mutation.mutate(v) })} noValidate className="space-y-4">
            <PickedProduct product={product} onChange={() => setProduct(undefined)} />
            {serverError && <Alert variant="destructive">{serverError}</Alert>}
            <div className="grid gap-4 sm:grid-cols-2">
              <Field id="restock-quantity" label={`Quantity (${product.unit})`} error={errors.quantity?.message}>
                <Input id="restock-quantity" inputMode="decimal" autoFocus invalid={!!errors.quantity} {...form.register('quantity')} />
              </Field>
              <Field id="restock-unit-cost" label="Cost per unit (KSh)" error={errors.unit_cost?.message}>
                <Input id="restock-unit-cost" inputMode="decimal" invalid={!!errors.unit_cost} {...form.register('unit_cost')} />
              </Field>
            </div>
            <Field id="restock-supplier" label="Supplier" optional error={errors.supplier_name?.message}>
              <Input id="restock-supplier" invalid={!!errors.supplier_name} {...form.register('supplier_name')} />
            </Field>
            <Field id="restock-reason" label="Note" optional error={errors.reason?.message}>
              <Input id="restock-reason" invalid={!!errors.reason} {...form.register('reason')} />
            </Field>
            <label className="flex items-start gap-3 text-sm">
              <Checkbox className="mt-0.5" {...form.register('update_cost_price')} />
              <span>Also make this the product's cost price</span>
            </label>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={mutation.isPending}>Cancel</Button>
              <Button type="submit" loading={mutation.isPending}>Add stock</Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  )
}

// --- Adjust --------------------------------------------------------------------

const adjustSchema = z.object({
  direction: z.enum(['DECREASE', 'INCREASE']),
  quantity,
  reason: z.string().trim().min(1, 'Say why the stock changed').max(255),
})
type AdjustValues = z.infer<typeof adjustSchema>

export function AdjustDialog({ open, onOpenChange, product: preset }: StockDialogProps) {
  const [product, setProduct] = useState<Product | undefined>(preset)
  const [serverError, setServerError] = useState<string | null>(null)
  const invalidate = useInvalidateStock()
  const form = useForm<AdjustValues>({ resolver: zodResolver(adjustSchema), defaultValues: { direction: 'DECREASE', quantity: '', reason: '' } })
  const mutation = useMutation({
    mutationFn: (values: AdjustValues) =>
      inventoryApi.adjust({ product_id: product!.id, quantity_delta: values.direction === 'DECREASE' ? `-${values.quantity}` : values.quantity, reason: values.reason }),
    onSuccess: (movement) => {
      invalidate()
      toast.success(`Stock is now ${formatQuantity(movement.quantity_after)} ${product?.unit ?? ''}`.trim())
      onOpenChange(false)
    },
    onError: (error) => setServerError(stockErrorMessage(error)),
  })
  function reset() { setProduct(preset); setServerError(null); form.reset() }
  const errors = form.formState.errors
  return (
    <Dialog open={open} onOpenChange={(o) => { onOpenChange(o); if (!o) reset() }}>
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Adjust stock</DialogTitle>
          <DialogDescription>Correct the count after a stock-take, damage or loss. The reason is kept for the record.</DialogDescription>
        </DialogHeader>
        {!product ? (
          <ProductPicker trackedOnly autoFocus onPick={setProduct} />
        ) : (
          <form onSubmit={form.handleSubmit((v) => { setServerError(null); mutation.mutate(v) })} noValidate className="space-y-4">
            <PickedProduct product={product} onChange={() => setProduct(undefined)} />
            {serverError && <Alert variant="destructive">{serverError}</Alert>}
            <div className="grid gap-4 sm:grid-cols-2">
              <Field id="adjust-direction" label="Change" error={errors.direction?.message}>
                <Select id="adjust-direction" {...form.register('direction')}>
                  <option value="DECREASE">Remove stock (less on hand)</option>
                  <option value="INCREASE">Add stock (more on hand)</option>
                </Select>
              </Field>
              <Field id="adjust-quantity" label={`Quantity (${product.unit})`} error={errors.quantity?.message}>
                <Input id="adjust-quantity" inputMode="decimal" autoFocus invalid={!!errors.quantity} {...form.register('quantity')} />
              </Field>
            </div>
            <Field id="adjust-reason" label="Reason" error={errors.reason?.message}>
              <Textarea id="adjust-reason" rows={2} placeholder="e.g. 2 packets damaged by rain" invalid={!!errors.reason} {...form.register('reason')} />
            </Field>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={mutation.isPending}>Cancel</Button>
              <Button type="submit" loading={mutation.isPending}>Save adjustment</Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  )
}

// --- Opening stock ----------------------------------------------------------------

const initialSchema = z.object({ quantity, unit_cost: money })
type InitialValues = z.infer<typeof initialSchema>

export function InitialStockDialog({ open, onOpenChange, product: preset }: StockDialogProps) {
  const [product, setProduct] = useState<Product | undefined>(preset)
  const [serverError, setServerError] = useState<string | null>(null)
  const invalidate = useInvalidateStock()
  const form = useForm<InitialValues>({ resolver: zodResolver(initialSchema), defaultValues: { quantity: '', unit_cost: preset?.cost_price ?? '' } })
  const mutation = useMutation({
    mutationFn: (values: InitialValues) => inventoryApi.initial({ product_id: product!.id, quantity: values.quantity, unit_cost: values.unit_cost }),
    onSuccess: (movement) => { invalidate(); toast.success(`Opening stock set to ${formatQuantity(movement.quantity_after)}`); onOpenChange(false) },
    onError: (error) => setServerError(stockErrorMessage(error)),
  })
  function reset() { setProduct(preset); setServerError(null); form.reset() }
  const errors = form.formState.errors
  return (
    <Dialog open={open} onOpenChange={(o) => { onOpenChange(o); if (!o) reset() }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Opening stock</DialogTitle>
          <DialogDescription>For a product that has never had stock recorded. Afterwards, use Restock and Adjust.</DialogDescription>
        </DialogHeader>
        {!product ? (
          <ProductPicker trackedOnly autoFocus onPick={(p) => { setProduct(p); form.setValue('unit_cost', p.cost_price ?? '') }} />
        ) : (
          <form onSubmit={form.handleSubmit((v) => { setServerError(null); mutation.mutate(v) })} noValidate className="space-y-4">
            <PickedProduct product={product} onChange={() => setProduct(undefined)} />
            {serverError && <Alert variant="destructive">{serverError}</Alert>}
            <div className="grid gap-4 sm:grid-cols-2">
              <Field id="initial-quantity" label={`Quantity (${product.unit})`} error={errors.quantity?.message}>
                <Input id="initial-quantity" inputMode="decimal" autoFocus invalid={!!errors.quantity} {...form.register('quantity')} />
              </Field>
              <Field id="initial-unit-cost" label="Cost per unit (KSh)" error={errors.unit_cost?.message}>
                <Input id="initial-unit-cost" inputMode="decimal" invalid={!!errors.unit_cost} {...form.register('unit_cost')} />
              </Field>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={mutation.isPending}>Cancel</Button>
              <Button type="submit" loading={mutation.isPending}>Set opening stock</Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  )
}
