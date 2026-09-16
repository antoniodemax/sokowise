import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { useNavigate } from 'react-router'
import { z } from 'zod'

import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { toast } from 'sonner'
import { ApiError } from '@/lib/api'
import { describeError, fieldErrors } from '@/lib/errors'

import { useAuth } from './auth-context'

const schema = z
  .object({
    current_password: z.string().min(1, 'Enter your current password'),
    new_password: z.string().min(8, 'Use at least 8 characters').max(128),
    confirm_password: z.string(),
  })
  .refine((values) => values.new_password === values.confirm_password, { path: ['confirm_password'], message: 'Passwords do not match' })
  .refine((values) => values.new_password !== values.current_password, { path: ['new_password'], message: 'Choose a different password from the current one' })
type FormValues = z.infer<typeof schema>

/**
 * Also the landing screen for PASSWORD_CHANGE_REQUIRED: the backend gates every
 * business endpoint until a staff member replaces the password their owner set.
 */
export default function ChangePasswordPage() {
  const { session, changePassword, logout } = useAuth()
  const navigate = useNavigate()
  const [serverError, setServerError] = useState<string | null>(null)
  const required = session?.user.must_change_password ?? false
  const { register, handleSubmit, setError, formState } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { current_password: '', new_password: '', confirm_password: '' },
  })

  async function onSubmit(values: FormValues) {
    setServerError(null)
    try {
      await changePassword({ current_password: values.current_password, new_password: values.new_password })
      toast.success('Password changed')
      navigate('/', { replace: true })
    } catch (error) {
      if (error instanceof ApiError && error.code === 'INVALID_CURRENT_PASSWORD') {
        setError('current_password', { message: 'That is not your current password' })
        return
      }
      const perField = fieldErrors(error)
      if (perField.new_password) setError('new_password', { message: perField.new_password })
      else setServerError(describeError(error))
    }
  }

  const errors = formState.errors
  return (
    <div>
      <h1 className="text-xl font-semibold">{required ? 'Set your own password' : 'Change password'}</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        {required
          ? `Welcome to ${session?.business.name ?? 'SokoWise'}. Before you start, replace the temporary password you were given.`
          : 'Everywhere else you are signed in will be signed out.'}
      </p>
      <form onSubmit={handleSubmit(onSubmit)} noValidate className="mt-6 space-y-4">
        {serverError && <Alert variant="destructive">{serverError}</Alert>}
        <Field id="current_password" label={required ? 'Temporary password' : 'Current password'} error={errors.current_password?.message}>
          <Input id="current_password" type="password" autoComplete="current-password" invalid={!!errors.current_password} {...register('current_password')} />
        </Field>
        <Field id="new_password" label="New password" error={errors.new_password?.message} hint="At least 8 characters">
          <Input id="new_password" type="password" autoComplete="new-password" invalid={!!errors.new_password} {...register('new_password')} />
        </Field>
        <Field id="confirm_password" label="Repeat new password" error={errors.confirm_password?.message}>
          <Input id="confirm_password" type="password" autoComplete="new-password" invalid={!!errors.confirm_password} {...register('confirm_password')} />
        </Field>
        <Button type="submit" className="w-full" size="lg" loading={formState.isSubmitting}>
          Save new password
        </Button>
        <Button
          type="button"
          variant="ghost"
          className="w-full"
          onClick={async () => {
            await logout()
            navigate('/login', { replace: true })
          }}
        >
          {required ? 'Sign out instead' : 'Cancel'}
        </Button>
      </form>
    </div>
  )
}
