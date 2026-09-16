import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'

import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { ApiError } from '@/lib/api'
import { describeError, fieldErrors } from '@/lib/errors'
import { queryKeys } from '@/lib/query-keys'

import { customersApi, type Customer } from './api'

const schema = z.object({
  name: z.string().trim().min(1, "Enter the customer's name").max(120),
  phone: z.string().trim().max(20),
  credit_limit: z.string().trim().regex(/^\d+(\.\d{1,2})?$/, 'Enter an amount like 2000').or(z.literal('')),
  notes: z.string().trim().max(2000),
})
type FormValues = z.infer<typeof schema>

export function CustomerFormDialog({ open, onOpenChange, onSaved }: { open: boolean; onOpenChange: (open: boolean) => void; onSaved?: (customer: Customer) => void }) {
  const queryClient = useQueryClient()
  const [serverError, setServerError] = useState<string | null>(null)
  const form = useForm<FormValues>({ resolver: zodResolver(schema), defaultValues: { name: '', phone: '', credit_limit: '', notes: '' } })
  const mutation = useMutation({
    mutationFn: (values: FormValues) => customersApi.create({ name: values.name, phone: values.phone || null, credit_limit: values.credit_limit || null, notes: values.notes || null }),
    onSuccess: (customer) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.customers.all })
      toast.success('Customer added')
      form.reset()
      onOpenChange(false)
      onSaved?.(customer)
    },
    onError: (error) => {
      if (error instanceof ApiError && error.code === 'CUSTOMER_PHONE_EXISTS') {
        form.setError('phone', { message: 'A customer with this phone number already exists' })
        return
      }
      const perField = fieldErrors(error)
      let handled = false
      for (const [field, message] of Object.entries(perField)) {
        if (field in form.getValues()) { form.setError(field as keyof FormValues, { message }); handled = true }
      }
      if (!handled) setServerError(describeError(error))
    },
  })
  const errors = form.formState.errors
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form onSubmit={form.handleSubmit((v) => { setServerError(null); mutation.mutate(v) })} noValidate className="space-y-4">
          <DialogHeader>
            <DialogTitle>Add a customer</DialogTitle>
            <DialogDescription>Someone you sell to on credit, or just want to keep track of.</DialogDescription>
          </DialogHeader>
          {serverError && <Alert variant="destructive">{serverError}</Alert>}
          <Field id="customer-name" label="Name" error={errors.name?.message}>
            <Input id="customer-name" autoFocus invalid={!!errors.name} {...form.register('name')} />
          </Field>
          <Field id="customer-phone" label="Phone" optional hint="07… or +254…" error={errors.phone?.message}>
            <Input id="customer-phone" type="tel" inputMode="tel" invalid={!!errors.phone} {...form.register('phone')} />
          </Field>
          <Field id="customer-limit" label="Credit limit (KSh)" optional hint="The most they may owe. Leave empty for no limit; 0 means no credit." error={errors.credit_limit?.message}>
            <Input id="customer-limit" inputMode="decimal" invalid={!!errors.credit_limit} {...form.register('credit_limit')} />
          </Field>
          <Field id="customer-notes" label="Notes" optional error={errors.notes?.message}>
            <Textarea id="customer-notes" rows={2} invalid={!!errors.notes} {...form.register('notes')} />
          </Field>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={mutation.isPending}>Cancel</Button>
            <Button type="submit" loading={mutation.isPending}>Add customer</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
