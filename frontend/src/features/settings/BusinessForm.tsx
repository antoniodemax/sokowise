import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'

import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { BUSINESS_TYPES } from '@/features/auth/api'
import { describeError, fieldErrors } from '@/lib/errors'
import { queryKeys } from '@/lib/query-keys'
import { sessionStore } from '@/lib/session'

import { businessApi, type Business } from './api'

const schema = z.object({
  name: z.string().trim().min(2, 'Enter the business name').max(120),
  business_type: z.string().min(1),
  phone: z.string().trim().max(20),
  address: z.string().trim().max(255),
  timezone: z.string().trim().min(1, 'Enter a time zone like Africa/Nairobi'),
  staff_can_restock: z.boolean(),
  sale_backdate_days: z.coerce.number().int('Whole days only').min(0).max(365),
  low_stock_default_threshold: z.coerce.number().int('Whole numbers only').min(0).max(100000),
})
type FormValues = z.infer<typeof schema>

export function BusinessForm({ business, onDone }: { business: Business; onDone: () => void }) {
  const queryClient = useQueryClient()
  const [serverError, setServerError] = useState<string | null>(null)
  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: business.name,
      business_type: business.business_type,
      phone: business.phone ?? '',
      address: business.address ?? '',
      timezone: business.timezone,
      staff_can_restock: business.settings.staff_can_restock ?? false,
      sale_backdate_days: business.settings.sale_backdate_days ?? 0,
      low_stock_default_threshold: business.settings.low_stock_default_threshold ?? 0,
    },
  })
  const mutation = useMutation({
    mutationFn: (values: FormValues) =>
      businessApi.update({
        name: values.name,
        business_type: values.business_type,
        phone: values.phone || null,
        address: values.address || null,
        timezone: values.timezone,
        settings: { staff_can_restock: values.staff_can_restock, sale_backdate_days: values.sale_backdate_days, low_stock_default_threshold: values.low_stock_default_threshold },
      }),
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.business.all, updated)
      sessionStore.updateBusiness({ name: updated.name, business_type: updated.business_type, timezone: updated.timezone })
      toast.success('Business details saved')
      onDone()
    },
    onError: (error) => {
      const perField = fieldErrors(error)
      let handled = false
      for (const [field, message] of Object.entries(perField)) if (field in form.getValues()) { form.setError(field as keyof FormValues, { message }); handled = true }
      if (!handled) setServerError(describeError(error))
    },
  })
  const errors = form.formState.errors
  return (
    <form onSubmit={form.handleSubmit((v) => { setServerError(null); mutation.mutate(v) })} noValidate className="space-y-4">
      {serverError && <Alert variant="destructive">{serverError}</Alert>}
      <Field id="biz-name" label="Business name" error={errors.name?.message}><Input id="biz-name" invalid={!!errors.name} {...form.register('name')} /></Field>
      <Field id="biz-type" label="Type" error={errors.business_type?.message}>
        <Select id="biz-type" {...form.register('business_type')}>{BUSINESS_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}</Select>
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field id="biz-phone" label="Business phone" optional error={errors.phone?.message}><Input id="biz-phone" type="tel" invalid={!!errors.phone} {...form.register('phone')} /></Field>
        <Field id="biz-tz" label="Time zone" hint="“Today” in reports follows this." error={errors.timezone?.message}><Input id="biz-tz" invalid={!!errors.timezone} {...form.register('timezone')} /></Field>
      </div>
      <Field id="biz-address" label="Address" optional error={errors.address?.message}><Input id="biz-address" invalid={!!errors.address} {...form.register('address')} /></Field>
      <fieldset className="space-y-4 rounded-lg border border-border p-4">
        <legend className="px-1 text-sm font-medium">How the shop runs</legend>
        <label className="flex items-start gap-3 text-sm">
          <Checkbox className="mt-0.5" {...form.register('staff_can_restock')} />
          <span>Staff can record restocks<span className="block text-xs text-muted-foreground">Otherwise only the owner adds stock.</span></span>
        </label>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field id="biz-backdate" label="Backdate sales up to (days)" hint="How far back the owner may date a sale. 0 = today only." error={errors.sale_backdate_days?.message}><Input id="biz-backdate" inputMode="numeric" invalid={!!errors.sale_backdate_days} {...form.register('sale_backdate_days')} /></Field>
          <Field id="biz-lowstock" label="Default low-stock alert" hint="Used for products without their own threshold." error={errors.low_stock_default_threshold?.message}><Input id="biz-lowstock" inputMode="numeric" invalid={!!errors.low_stock_default_threshold} {...form.register('low_stock_default_threshold')} /></Field>
        </div>
      </fieldset>
      <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <Button type="button" variant="outline" onClick={onDone} disabled={mutation.isPending}>Cancel</Button>
        <Button type="submit" loading={mutation.isPending}>Save changes</Button>
      </div>
    </form>
  )
}
