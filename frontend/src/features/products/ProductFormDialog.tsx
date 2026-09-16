import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useForm, useWatch } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'

import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { ApiError } from '@/lib/api'
import { describeError, fieldErrors } from '@/lib/errors'
import { queryKeys } from '@/lib/query-keys'

import { PRODUCT_UNITS, productsApi, type Product, type ProductCreate, type ProductUpdate } from './api'
import { useCategories } from './hooks'

const money = z.string().trim().regex(/^\d+(\.\d{1,2})?$/, 'Enter an amount like 150 or 150.50')
const quantity = z.string().trim().regex(/^\d+(\.\d{1,3})?$/, 'Enter a quantity like 10 or 2.5')

const schema = z
  .object({
    name: z.string().trim().min(1, 'Enter the product name').max(120),
    category_id: z.string(),
    sku: z.string().trim().max(60),
    barcode: z.string().trim().max(64),
    unit: z.enum(PRODUCT_UNITS),
    selling_price: money,
    cost_price: money.or(z.literal('')),
    track_inventory: z.boolean(),
    low_stock_threshold: quantity.or(z.literal('')),
    opening_stock: quantity.or(z.literal('')),
    opening_unit_cost: money.or(z.literal('')),
  })
  .superRefine((values, ctx) => {
    if (values.opening_stock && !values.track_inventory) ctx.addIssue({ code: 'custom', path: ['opening_stock'], message: 'Only stock-tracked products can have opening stock' })
    if (values.opening_stock && !values.opening_unit_cost && !values.cost_price) ctx.addIssue({ code: 'custom', path: ['opening_unit_cost'], message: 'Enter what you paid per unit (or a cost price)' })
  })
type FormValues = z.infer<typeof schema>

const CONFLICT_FIELDS: Record<string, keyof FormValues> = { PRODUCT_NAME_EXISTS: 'name', SKU_EXISTS: 'sku', BARCODE_EXISTS: 'barcode' }

interface ProductFormDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Editing when given; creating otherwise. */
  product?: Product
  onSaved?: (product: Product) => void
}

export function ProductFormDialog({ open, onOpenChange, product, onSaved }: ProductFormDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-xl">
        {open && <ProductForm product={product} onDone={(saved) => { onSaved?.(saved); onOpenChange(false) }} onCancel={() => onOpenChange(false)} />}
      </DialogContent>
    </Dialog>
  )
}

function ProductForm({ product, onDone, onCancel }: { product?: Product; onDone: (product: Product) => void; onCancel: () => void }) {
  const queryClient = useQueryClient()
  const categories = useCategories()
  const [serverError, setServerError] = useState<string | null>(null)
  const editing = !!product
  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: product?.name ?? '',
      category_id: product?.category_id ?? '',
      sku: product?.sku ?? '',
      barcode: product?.barcode ?? '',
      unit: product?.unit ?? 'piece',
      selling_price: product?.selling_price ?? '',
      cost_price: product?.cost_price ?? '',
      track_inventory: product?.track_inventory ?? true,
      low_stock_threshold: product?.low_stock_threshold ?? '',
      opening_stock: '',
      opening_unit_cost: '',
    },
  })
  const tracked = useWatch({ control: form.control, name: 'track_inventory' })

  const mutation = useMutation({
    mutationFn: async (values: FormValues) => {
      const base = {
        name: values.name,
        category_id: values.category_id || null,
        sku: values.sku || null,
        barcode: values.barcode || null,
        unit: values.unit,
        selling_price: values.selling_price,
        cost_price: values.cost_price || null,
        track_inventory: values.track_inventory,
        low_stock_threshold: values.low_stock_threshold || null,
      }
      if (editing) {
        const update: ProductUpdate = base
        return productsApi.update(product.id, update)
      }
      const create: ProductCreate = { ...base, opening_stock: values.opening_stock || null, opening_unit_cost: values.opening_unit_cost || null }
      return productsApi.create(create)
    },
    onSuccess: (saved) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.products.all })
      void queryClient.invalidateQueries({ queryKey: queryKeys.inventory.all })
      toast.success(editing ? 'Product updated' : 'Product added')
      onDone(saved)
    },
    onError: (error) => {
      if (error instanceof ApiError && error.code in CONFLICT_FIELDS) {
        form.setError(CONFLICT_FIELDS[error.code], { message: error.message })
        return
      }
      const perField = fieldErrors(error)
      let handled = false
      for (const [field, message] of Object.entries(perField)) {
        if (field in form.getValues()) {
          form.setError(field as keyof FormValues, { message })
          handled = true
        }
      }
      if (!handled) setServerError(describeError(error))
    },
  })

  const errors = form.formState.errors
  return (
    <form onSubmit={form.handleSubmit((values) => { setServerError(null); mutation.mutate(values) })} noValidate className="space-y-4">
      <DialogHeader>
        <DialogTitle>{editing ? 'Edit product' : 'Add a product'}</DialogTitle>
        <DialogDescription>{editing ? 'Prices you change here apply to new sales only; past sales keep the price they were sold at.' : 'Name and selling price are all you need to start selling.'}</DialogDescription>
      </DialogHeader>
      {serverError && <Alert variant="destructive">{serverError}</Alert>}
      <Field id="name" label="Product name" error={errors.name?.message}>
        <Input id="name" autoFocus invalid={!!errors.name} {...form.register('name')} />
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field id="selling_price" label="Selling price (KSh)" error={errors.selling_price?.message}>
          <Input id="selling_price" inputMode="decimal" placeholder="0.00" invalid={!!errors.selling_price} {...form.register('selling_price')} />
        </Field>
        <Field id="cost_price" label="Cost price (KSh)" optional hint="What you pay per unit. Needed to see profit." error={errors.cost_price?.message}>
          <Input id="cost_price" inputMode="decimal" placeholder="0.00" invalid={!!errors.cost_price} {...form.register('cost_price')} />
        </Field>
        <Field id="unit" label="Unit" error={errors.unit?.message}>
          <Select id="unit" {...form.register('unit')}>
            {PRODUCT_UNITS.map((unit) => (
              <option key={unit} value={unit}>{unit}</option>
            ))}
          </Select>
        </Field>
        <Field id="category_id" label="Category" optional error={errors.category_id?.message}>
          <Select id="category_id" {...form.register('category_id')}>
            <option value="">No category</option>
            {(categories.data ?? []).map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </Select>
        </Field>
        <Field id="sku" label="SKU / code" optional error={errors.sku?.message}>
          <Input id="sku" invalid={!!errors.sku} {...form.register('sku')} />
        </Field>
        <Field id="barcode" label="Barcode" optional error={errors.barcode?.message}>
          <Input id="barcode" inputMode="numeric" invalid={!!errors.barcode} {...form.register('barcode')} />
        </Field>
      </div>
      <label className="flex items-start gap-3 rounded-lg border border-border p-3">
        <Checkbox className="mt-0.5" {...form.register('track_inventory')} />
        <span>
          <span className="block text-sm font-medium">Track stock for this product</span>
          <span className="block text-xs text-muted-foreground">Turn off for services (haircuts, repairs) and things you never count.</span>
        </span>
      </label>
      {tracked && (
        <div className="grid gap-4 sm:grid-cols-2">
          <Field id="low_stock_threshold" label="Low-stock alert at" optional hint="Leave empty to use the business default." error={errors.low_stock_threshold?.message}>
            <Input id="low_stock_threshold" inputMode="decimal" invalid={!!errors.low_stock_threshold} {...form.register('low_stock_threshold')} />
          </Field>
          {!editing && (
            <>
              <Field id="opening_stock" label="Stock on hand now" optional error={errors.opening_stock?.message}>
                <Input id="opening_stock" inputMode="decimal" invalid={!!errors.opening_stock} {...form.register('opening_stock')} />
              </Field>
              <Field id="opening_unit_cost" label="Cost per unit of that stock (KSh)" optional hint="Defaults to the cost price." error={errors.opening_unit_cost?.message}>
                <Input id="opening_unit_cost" inputMode="decimal" invalid={!!errors.opening_unit_cost} {...form.register('opening_unit_cost')} />
              </Field>
            </>
          )}
        </div>
      )}
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onCancel} disabled={mutation.isPending}>Cancel</Button>
        <Button type="submit" loading={mutation.isPending}>{editing ? 'Save changes' : 'Add product'}</Button>
      </DialogFooter>
    </form>
  )
}
