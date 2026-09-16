import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useForm, useWatch } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'

import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { ApiError } from '@/lib/api'
import { describeError, fieldErrors } from '@/lib/errors'
import { queryKeys } from '@/lib/query-keys'

import { expensesApi, type Expense } from './api'

const schema = z.object({
  amount: z.string().trim().regex(/^\d+(\.\d{1,2})?$/, 'Enter an amount like 500 or 500.50').refine((v) => Number(v) > 0, 'Amount must be more than zero'),
  category: z.string().trim().min(1, 'Pick or type a category').max(50),
  payment_method: z.enum(['CASH', 'MPESA']),
  reference: z.string().trim().max(64),
  note: z.string().trim().max(500),
  incurred_at: z.string().min(1, 'When was this paid?'),
})
type FormValues = z.infer<typeof schema>

/** datetime-local value for an instant, in the browser's clock. */
function toLocalInput(iso?: string): string {
  const d = iso ? new Date(iso) : new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function ExpenseFormDialog({ open, onOpenChange, expense }: { open: boolean; onOpenChange: (open: boolean) => void; expense?: Expense | null }) {
  const queryClient = useQueryClient()
  const [serverError, setServerError] = useState<string | null>(null)
  const suggestions = useQuery({ queryKey: queryKeys.expenses.categories, queryFn: ({ signal }) => expensesApi.categories(signal), staleTime: 5 * 60_000 })
  const form = useForm<FormValues>({ resolver: zodResolver(schema), defaultValues: { amount: '', category: '', payment_method: 'CASH', reference: '', note: '', incurred_at: toLocalInput() } })
  useEffect(() => {
    if (open) form.reset(expense ? { amount: expense.amount, category: expense.category, payment_method: expense.payment_method, reference: expense.reference ?? '', note: expense.note ?? '', incurred_at: toLocalInput(expense.incurred_at) } : { amount: '', category: '', payment_method: 'CASH', reference: '', note: '', incurred_at: toLocalInput() })
  }, [open, expense, form])
  const method = useWatch({ control: form.control, name: 'payment_method' })

  const mutation = useMutation({
    mutationFn: (values: FormValues) => {
      const body = { amount: values.amount, category: values.category, payment_method: values.payment_method, reference: values.reference || null, note: values.note || null, incurred_at: new Date(values.incurred_at).toISOString() }
      return expense ? expensesApi.update(expense.id, body) : expensesApi.create(body)
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.expenses.all })
      void queryClient.invalidateQueries({ queryKey: queryKeys.analytics.all })
      toast.success(expense ? 'Expense updated' : 'Expense recorded')
      onOpenChange(false)
    },
    onError: (error) => {
      if (error instanceof ApiError && error.code === 'EXPENSE_IN_FUTURE') { form.setError('incurred_at', { message: 'That time is in the future.' }); return }
      if (error instanceof ApiError && error.code === 'EXPENSE_DELETED') { setServerError('This expense was deleted and can no longer be edited.'); return }
      const perField = fieldErrors(error)
      let handled = false
      for (const [field, message] of Object.entries(perField)) if (field in form.getValues()) { form.setError(field as keyof FormValues, { message }); handled = true }
      if (!handled) setServerError(describeError(error))
    },
  })
  const errors = form.formState.errors
  return (
    <Dialog open={open} onOpenChange={(o) => { onOpenChange(o); if (!o) setServerError(null) }}>
      <DialogContent>
        <form onSubmit={form.handleSubmit((v) => { setServerError(null); mutation.mutate(v) })} noValidate className="space-y-4">
          <DialogHeader>
            <DialogTitle>{expense ? 'Edit expense' : 'Record an expense'}</DialogTitle>
            <DialogDescription>Running costs like rent, transport or airtime. Buying stock is a restock under Inventory, not an expense.</DialogDescription>
          </DialogHeader>
          {serverError && <Alert variant="destructive">{serverError}</Alert>}
          <div className="grid gap-4 sm:grid-cols-2">
            <Field id="expense-amount" label="Amount (KSh)" error={errors.amount?.message}>
              <Input id="expense-amount" inputMode="decimal" autoFocus invalid={!!errors.amount} {...form.register('amount')} />
            </Field>
            <Field id="expense-category" label="Category" error={errors.category?.message}>
              <Input id="expense-category" list="expense-categories" autoComplete="off" invalid={!!errors.category} {...form.register('category')} />
              <datalist id="expense-categories">{(suggestions.data?.suggested ?? []).map((c) => <option key={c} value={c} />)}</datalist>
            </Field>
            <Field id="expense-method" label="Paid by" error={errors.payment_method?.message}>
              <Select id="expense-method" {...form.register('payment_method')}>
                <option value="CASH">Cash</option>
                <option value="MPESA">M-Pesa</option>
              </Select>
            </Field>
            <Field id="expense-at" label="When" error={errors.incurred_at?.message}>
              <Input id="expense-at" type="datetime-local" invalid={!!errors.incurred_at} {...form.register('incurred_at')} />
            </Field>
          </div>
          {method === 'MPESA' && (
            <Field id="expense-reference" label="M-Pesa code" optional hint="For your records — not verified." error={errors.reference?.message}>
              <Input id="expense-reference" invalid={!!errors.reference} {...form.register('reference')} />
            </Field>
          )}
          <Field id="expense-note" label="Note" optional error={errors.note?.message}>
            <Textarea id="expense-note" rows={2} className="min-h-0" invalid={!!errors.note} {...form.register('note')} />
          </Field>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={mutation.isPending}>Cancel</Button>
            <Button type="submit" loading={mutation.isPending}>{expense ? 'Save changes' : 'Record expense'}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
