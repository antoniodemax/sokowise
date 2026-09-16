import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, useNavigate } from 'react-router'
import { z } from 'zod'

import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { ApiError } from '@/lib/api'
import { describeError, fieldErrors } from '@/lib/errors'

import { BUSINESS_TYPES } from './api'
import { useAuth } from './auth-context'

// Mirrors the backend contract (PRD FR-A1, FR-B1): the server does the real
// validation and phone normalisation; these checks only catch obvious slips early.
const schema = z.object({
  full_name: z.string().trim().min(1, 'Enter your name').max(120),
  phone: z.string().trim().min(9, 'Enter a valid phone number, e.g. 0712 345 678').max(20),
  email: z.string().trim().email('Enter a valid email address').max(255).or(z.literal('')),
  password: z.string().min(8, 'Use at least 8 characters').max(128),
  business_name: z.string().trim().min(1, "Enter your business's name").max(120),
  business_type: z.string().min(1),
})
type FormValues = z.infer<typeof schema>

export default function RegisterPage() {
  const { register: registerBusiness } = useAuth()
  const navigate = useNavigate()
  const [serverError, setServerError] = useState<string | null>(null)
  const { register, handleSubmit, setError, formState } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { full_name: '', phone: '', email: '', password: '', business_name: '', business_type: 'GENERAL_SHOP' },
  })

  async function onSubmit(values: FormValues) {
    setServerError(null)
    try {
      await registerBusiness({ ...values, email: values.email || null })
      navigate('/', { replace: true })
    } catch (error) {
      const perField = fieldErrors(error)
      for (const [field, message] of Object.entries(perField)) {
        if (field in values) setError(field as keyof FormValues, { message })
      }
      if (error instanceof ApiError && error.code === 'ACCOUNT_EXISTS') {
        setServerError('An account with this phone number or email already exists. Try signing in instead.')
      } else if (Object.keys(perField).length === 0) {
        setServerError(describeError(error))
      }
    }
  }

  const errors = formState.errors
  const describedBy = (name: keyof FormValues) => (errors[name] ? `${name}-error` : undefined)

  return (
    <div>
      <h1 className="text-xl font-semibold">Create your business</h1>
      <p className="mt-1 text-sm text-muted-foreground">One account for you, one workspace for your shop. Takes a minute.</p>
      <form onSubmit={handleSubmit(onSubmit)} noValidate className="mt-6 space-y-4">
        {serverError && <Alert variant="destructive">{serverError}</Alert>}
        <fieldset className="space-y-4">
          <legend className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">About you</legend>
          <Field id="full_name" label="Your name" error={errors.full_name?.message}>
            <Input id="full_name" autoComplete="name" invalid={!!errors.full_name} aria-describedby={describedBy('full_name')} {...register('full_name')} />
          </Field>
          <Field id="phone" label="Phone number" error={errors.phone?.message} hint="Kenyan numbers work as 07… or +254…">
            <Input id="phone" type="tel" autoComplete="tel" inputMode="tel" placeholder="0712 345 678" invalid={!!errors.phone} aria-describedby={describedBy('phone') ?? 'phone-hint'} {...register('phone')} />
          </Field>
          <Field id="email" label="Email" optional error={errors.email?.message}>
            <Input id="email" type="email" autoComplete="email" inputMode="email" invalid={!!errors.email} aria-describedby={describedBy('email')} {...register('email')} />
          </Field>
          <Field id="password" label="Password" error={errors.password?.message} hint="At least 8 characters">
            <Input id="password" type="password" autoComplete="new-password" invalid={!!errors.password} aria-describedby={describedBy('password') ?? 'password-hint'} {...register('password')} />
          </Field>
        </fieldset>
        <fieldset className="space-y-4">
          <legend className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">Your business</legend>
          <Field id="business_name" label="Business name" error={errors.business_name?.message}>
            <Input id="business_name" autoComplete="organization" placeholder="Amina Duka" invalid={!!errors.business_name} aria-describedby={describedBy('business_name')} {...register('business_name')} />
          </Field>
          <Field id="business_type" label="Type of business" error={errors.business_type?.message}>
            <Select id="business_type" invalid={!!errors.business_type} {...register('business_type')}>
              {BUSINESS_TYPES.map((type) => (
                <option key={type.value} value={type.value}>
                  {type.label}
                </option>
              ))}
            </Select>
          </Field>
        </fieldset>
        <Button type="submit" className="w-full" size="lg" loading={formState.isSubmitting}>
          Create business
        </Button>
      </form>
      <p className="mt-6 text-center text-sm text-muted-foreground">
        Already have an account?{' '}
        <Link to="/login" className="font-medium text-primary underline-offset-4 hover:underline">
          Sign in
        </Link>
      </p>
    </div>
  )
}
