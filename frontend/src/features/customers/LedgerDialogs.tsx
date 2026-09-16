import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
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
import { describeError } from '@/lib/errors'
import { useIdempotencyKey } from '@/lib/idempotency'
import { formatKsh } from '@/lib/money'
import { queryKeys } from '@/lib/query-keys'

import { customersApi, type Customer } from './api'

const money = z.string().trim().regex(/^\d+(\.\d{1,2})?$/, 'Enter an amount like 500 or 500.50').refine((v) => Number(v) > 0, 'Amount must be more than zero')

function useInvalidateCustomer(customerId: string) {
  const queryClient = useQueryClient()
  return () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.customers.all })
    void queryClient.invalidateQueries({ queryKey: queryKeys.customers.detail(customerId) })
    void queryClient.invalidateQueries({ queryKey: queryKeys.analytics.all })
  }
}

const repaymentSchema = z.object({ amount: money, payment_method: z.enum(['CASH', 'MPESA']), reference: z.string().trim().max(64) })
type RepaymentValues = z.infer<typeof repaymentSchema>

export function RepaymentDialog({ customer, open, onOpenChange }: { customer: Customer; open: boolean; onOpenChange: (open: boolean) => void }) {
  const invalidate = useInvalidateCustomer(customer.id)
  const key = useIdempotencyKey()
  const [serverError, setServerError] = useState<string | null>(null)
  const [overpay, setOverpay] = useState(false)
  const form = useForm<RepaymentValues>({ resolver: zodResolver(repaymentSchema), defaultValues: { amount: '', payment_method: 'CASH', reference: '' } })
  const method = useWatch({ control: form.control, name: 'payment_method' })
  const mutation = useMutation({
    mutationFn: (values: RepaymentValues) => {
      const body = { amount: values.amount, payment_method: values.payment_method, reference: values.reference || null, allow_overpayment: overpay }
      return customersApi.repay(customer.id, body, key.keyFor(body))
    },
    onSuccess: (entry) => {
      key.renew()
      invalidate()
      toast.success(`Repayment recorded. ${Number(entry.balance_after) > 0 ? `Still owes ${formatKsh(entry.balance_after)}.` : 'Fully paid up.'}`)
      form.reset()
      setOverpay(false)
      onOpenChange(false)
    },
    onError: (error) => {
      if (error instanceof ApiError && error.code === 'REPAYMENT_EXCEEDS_BALANCE') {
        setServerError(`That is more than the ${formatKsh(customer.balance)} owed. Tick the box below if the customer is paying extra in advance.`)
        return
      }
      setServerError(describeError(error))
    },
  })
  const errors = form.formState.errors
  return (
    <Dialog open={open} onOpenChange={(o) => { onOpenChange(o); if (!o) { setServerError(null); setOverpay(false) } }}>
      <DialogContent>
        <form onSubmit={form.handleSubmit((v) => { setServerError(null); mutation.mutate(v) })} noValidate className="space-y-4">
          <DialogHeader>
            <DialogTitle>Record a repayment</DialogTitle>
            <DialogDescription>{customer.name} owes {formatKsh(customer.balance)}. Money received here reduces that; it is not a sale.</DialogDescription>
          </DialogHeader>
          {serverError && <Alert variant="destructive">{serverError}</Alert>}
          <div className="grid gap-4 sm:grid-cols-2">
            <Field id="repay-amount" label="Amount (KSh)" error={errors.amount?.message}>
              <Input id="repay-amount" inputMode="decimal" autoFocus invalid={!!errors.amount} {...form.register('amount')} />
            </Field>
            <Field id="repay-method" label="Paid by" error={errors.payment_method?.message}>
              <Select id="repay-method" {...form.register('payment_method')}>
                <option value="CASH">Cash</option>
                <option value="MPESA">M-Pesa</option>
              </Select>
            </Field>
          </div>
          {method === 'MPESA' && (
            <Field id="repay-reference" label="M-Pesa code" optional hint="Typed in for your records — not checked with Safaricom." error={errors.reference?.message}>
              <Input id="repay-reference" invalid={!!errors.reference} {...form.register('reference')} />
            </Field>
          )}
          {serverError?.includes('advance') && (
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" className="size-5 accent-primary" checked={overpay} onChange={(e) => setOverpay(e.target.checked)} /> The customer is paying extra in advance
            </label>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={mutation.isPending}>Cancel</Button>
            <Button type="submit" loading={mutation.isPending}>Record repayment</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

const adjustmentSchema = z.object({ direction: z.enum(['DECREASE', 'INCREASE']), amount: money, reason: z.string().trim().min(1, 'Say why the balance changes').max(255) })
type AdjustmentValues = z.infer<typeof adjustmentSchema>

export function AdjustmentDialog({ customer, open, onOpenChange }: { customer: Customer; open: boolean; onOpenChange: (open: boolean) => void }) {
  const invalidate = useInvalidateCustomer(customer.id)
  const key = useIdempotencyKey()
  const [serverError, setServerError] = useState<string | null>(null)
  const form = useForm<AdjustmentValues>({ resolver: zodResolver(adjustmentSchema), defaultValues: { direction: 'DECREASE', amount: '', reason: '' } })
  const mutation = useMutation({
    mutationFn: (values: AdjustmentValues) => customersApi.adjust(customer.id, values, key.keyFor(values)),
    onSuccess: (entry) => { key.renew(); invalidate(); toast.success(`Balance is now ${formatKsh(entry.balance_after)}`); form.reset(); onOpenChange(false) },
    onError: (error) => {
      if (error instanceof ApiError && error.code === 'ADJUSTMENT_EXCEEDS_BALANCE') {
        setServerError(`You can reduce the balance by at most ${formatKsh(customer.balance)}. To record extra money received, use a repayment.`)
        return
      }
      setServerError(describeError(error))
    },
  })
  const errors = form.formState.errors
  return (
    <Dialog open={open} onOpenChange={(o) => { onOpenChange(o); if (!o) setServerError(null) }}>
      <DialogContent>
        <form onSubmit={form.handleSubmit((v) => { setServerError(null); mutation.mutate(v) })} noValidate className="space-y-4">
          <DialogHeader>
            <DialogTitle>Adjust balance</DialogTitle>
            <DialogDescription>Owner correction with a reason — for a forgotten sale, a goodwill write-off, or a mistake. Money received is a repayment, not an adjustment.</DialogDescription>
          </DialogHeader>
          {serverError && <Alert variant="destructive">{serverError}</Alert>}
          <div className="grid gap-4 sm:grid-cols-2">
            <Field id="adj-direction" label="Change" error={errors.direction?.message}>
              <Select id="adj-direction" {...form.register('direction')}>
                <option value="DECREASE">Reduce what they owe</option>
                <option value="INCREASE">Increase what they owe</option>
              </Select>
            </Field>
            <Field id="adj-amount" label="Amount (KSh)" error={errors.amount?.message}>
              <Input id="adj-amount" inputMode="decimal" autoFocus invalid={!!errors.amount} {...form.register('amount')} />
            </Field>
          </div>
          <Field id="adj-reason" label="Reason" error={errors.reason?.message}>
            <Textarea id="adj-reason" rows={2} invalid={!!errors.reason} {...form.register('reason')} />
          </Field>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={mutation.isPending}>Cancel</Button>
            <Button type="submit" loading={mutation.isPending}>Save adjustment</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
