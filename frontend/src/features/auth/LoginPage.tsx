import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, useLocation, useNavigate } from 'react-router'
import { z } from 'zod'

import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { describeError } from '@/lib/errors'

import { useAuth } from './auth-context'

const schema = z.object({
  identifier: z.string().trim().min(1, 'Enter your phone number or email'),
  password: z.string().min(1, 'Enter your password'),
})
type FormValues = z.infer<typeof schema>

export default function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [serverError, setServerError] = useState<string | null>(null)
  const { register, handleSubmit, formState } = useForm<FormValues>({ resolver: zodResolver(schema), defaultValues: { identifier: '', password: '' } })

  async function onSubmit(values: FormValues) {
    setServerError(null)
    try {
      const session = await login(values)
      const from = (location.state as { from?: string } | null)?.from
      navigate(session.user.must_change_password ? '/change-password' : (from ?? '/'), { replace: true })
    } catch (error) {
      setServerError(describeError(error))
    }
  }

  return (
    <div>
      <h1 className="text-xl font-semibold">Sign in</h1>
      <p className="mt-1 text-sm text-muted-foreground">Welcome back. Use the phone number or email you registered with.</p>
      <form onSubmit={handleSubmit(onSubmit)} noValidate className="mt-6 space-y-4">
        {serverError && <Alert variant="destructive">{serverError}</Alert>}
        <Field id="identifier" label="Phone number or email" error={formState.errors.identifier?.message}>
          <Input
            id="identifier"
            autoComplete="username"
            inputMode="email"
            placeholder="0712 345 678"
            invalid={!!formState.errors.identifier}
            aria-describedby={formState.errors.identifier ? 'identifier-error' : undefined}
            {...register('identifier')}
          />
        </Field>
        <Field id="password" label="Password" error={formState.errors.password?.message}>
          <Input
            id="password"
            type="password"
            autoComplete="current-password"
            invalid={!!formState.errors.password}
            aria-describedby={formState.errors.password ? 'password-error' : undefined}
            {...register('password')}
          />
        </Field>
        <Button type="submit" className="w-full" size="lg" loading={formState.isSubmitting}>
          Sign in
        </Button>
      </form>
      <p className="mt-6 text-center text-sm text-muted-foreground">
        New to SokoWise?{' '}
        <Link to="/register" className="font-medium text-primary underline-offset-4 hover:underline">
          Create your business
        </Link>
      </p>
    </div>
  )
}
