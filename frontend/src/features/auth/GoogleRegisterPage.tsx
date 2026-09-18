import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, Navigate, useLocation, useNavigate } from 'react-router'
import { z } from 'zod'

import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { ApiError } from '@/lib/api'
import { describeError, fieldErrors } from '@/lib/errors'

import { BUSINESS_TYPES, type GoogleSignupPending } from './api'
import { useAuth } from './auth-context'

const schema = z.object({
  full_name: z.string().trim().min(1, 'Enter your name').max(120),
  phone: z.string().trim().min(7, 'Enter your phone number').max(20),
  business_name: z.string().trim().min(1, 'Enter your business name').max(120),
  business_type: z.string().min(1),
})
type FormValues = z.infer<typeof schema>

/** The finish-up form after a Google sign-in with no account yet: phone and business. */
export default function GoogleRegisterPage() {
  const pending = (useLocation().state ?? null) as GoogleSignupPending | null
  const { registerWithGoogle } = useAuth()
  const navigate = useNavigate()
  const [serverError, setServerError] = useState<string | null>(null)
  const { register, handleSubmit, formState, setError } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { full_name: pending?.name ?? '', phone: '', business_name: '', business_type: 'GENERAL_SHOP' },
  })
  if (!pending?.registration_token) return <Navigate to="/login" replace />

  async function onSubmit(values: FormValues) {
    if (!pending) return
    setServerError(null)
    try {
      await registerWithGoogle({ ...values, registration_token: pending.registration_token })
      navigate('/dashboard', { replace: true })
    } catch (error) {
      const perField = fieldErrors(error)
      for (const [field, message] of Object.entries(perField)) {
        if (field in values) setError(field as keyof FormValues, { message })
      }
      if (error instanceof ApiError && error.code === 'ACCOUNT_EXISTS') {
        setServerError('An account with this phone number already exists. Sign in with your password, or use Forgot password.')
      } else if (error instanceof ApiError && error.code === 'SIGNUP_TOKEN_INVALID') {
        setServerError('That Google sign-in has expired. Go back and tap the Google button again.')
      } else if (Object.keys(perField).length === 0) {
        setServerError(describeError(error))
      }
    }
  }

  const errors = formState.errors
  return (
    <div>
      <h1 className="text-xl font-semibold">Almost there</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        Signed in with Google as <span className="font-medium text-foreground">{pending.email}</span>. Add your phone number and business to finish.
      </p>
      <form onSubmit={handleSubmit(onSubmit)} noValidate className="mt-6 space-y-4">
        {serverError && <Alert variant="destructive" role="alert">{serverError}</Alert>}
        <Field id="full_name" label="Your name" error={errors.full_name?.message}>
          <Input id="full_name" autoComplete="name" invalid={!!errors.full_name} {...register('full_name')} />
        </Field>
        <Field id="phone" label="Phone number" hint="Kenyan numbers work as 07… or +254…" error={errors.phone?.message}>
          <Input id="phone" type="tel" inputMode="tel" autoComplete="tel" placeholder="0712 345 678" invalid={!!errors.phone} {...register('phone')} />
        </Field>
        <Field id="business_name" label="Business name" error={errors.business_name?.message}>
          <Input id="business_name" autoComplete="organization" placeholder="Amina Duka" invalid={!!errors.business_name} {...register('business_name')} />
        </Field>
        <Field id="business_type" label="Type of business" error={errors.business_type?.message}>
          <Select id="business_type" invalid={!!errors.business_type} {...register('business_type')}>
            {BUSINESS_TYPES.map((type) => (
              <option key={type.value} value={type.value}>{type.label}</option>
            ))}
          </Select>
        </Field>
        <Button type="submit" className="w-full" size="lg" loading={formState.isSubmitting}>Create business</Button>
      </form>
      <p className="mt-6 text-center text-sm text-muted-foreground">
        Changed your mind? <Link to="/login" className="font-medium text-primary underline-offset-4 hover:underline">Back to sign in</Link>
      </p>
    </div>
  )
}
