import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link } from 'react-router'
import { z } from 'zod'

import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { ApiError } from '@/lib/api'
import { describeError, fieldErrors } from '@/lib/errors'

import { authApi } from './api'

const phoneSchema = z.object({ phone: z.string().trim().min(7, 'Enter your phone number').max(20) })
const codeSchema = z
  .object({
    code: z.string().trim().regex(/^\d{6}$/, 'Enter the 6-digit code from the SMS'),
    new_password: z.string().min(8, 'At least 8 characters').max(128),
    confirm: z.string(),
  })
  .refine((v) => v.new_password === v.confirm, { path: ['confirm'], message: 'The two passwords do not match' })
type PhoneValues = z.infer<typeof phoneSchema>
type CodeValues = z.infer<typeof codeSchema>

const NOT_AVAILABLE = 'Password reset by SMS is not switched on in this test version yet. Contact the SokoWise team and we will reset it for you.'

/** Two steps: phone → SMS code + new password. Never says whether a phone is registered. */
export default function ForgotPasswordPage() {
  const [phone, setPhone] = useState<string | null>(null)
  const [done, setDone] = useState(false)
  const [serverError, setServerError] = useState<string | null>(null)
  const phoneForm = useForm<PhoneValues>({ resolver: zodResolver(phoneSchema), defaultValues: { phone: '' } })
  const codeForm = useForm<CodeValues>({ resolver: zodResolver(codeSchema), defaultValues: { code: '', new_password: '', confirm: '' } })

  function explain(error: unknown): string {
    if (error instanceof ApiError && (error.code === 'PASSWORD_RESET_NOT_CONFIGURED')) return NOT_AVAILABLE
    if (error instanceof ApiError && error.code === 'SMS_UNAVAILABLE') return error.message
    if (error instanceof ApiError && error.code === 'RESET_CODE_INVALID') return 'That code is not valid or has expired. Check the SMS, or ask for a new code.'
    return describeError(error)
  }

  async function requestCode(values: PhoneValues) {
    setServerError(null)
    try {
      await authApi.requestPasswordReset(values.phone)
      setPhone(values.phone)
    } catch (error) {
      setServerError(explain(error))
    }
  }

  async function confirm(values: CodeValues) {
    if (!phone) return
    setServerError(null)
    try {
      await authApi.confirmPasswordReset({ phone, code: values.code, new_password: values.new_password })
      setDone(true)
    } catch (error) {
      const perField = fieldErrors(error)
      if (perField.new_password) codeForm.setError('new_password', { message: perField.new_password })
      else setServerError(explain(error))
    }
  }

  if (done) {
    return (
      <div>
        <h1 className="text-xl font-semibold">Password changed</h1>
        <p className="mt-1 text-sm text-muted-foreground">Sign in with your new password. Any other phone that was signed in has been signed out.</p>
        <Link to="/login" className="mt-6 block"><Button type="button" className="w-full" size="lg">Sign in</Button></Link>
      </div>
    )
  }

  if (phone) {
    return (
      <div>
        <h1 className="text-xl font-semibold">Check your SMS</h1>
        <p className="mt-1 text-sm text-muted-foreground">If <span className="font-medium text-foreground">{phone}</span> has a SokoWise account, a 6-digit code is on its way. It works for 10 minutes.</p>
        <form onSubmit={codeForm.handleSubmit(confirm)} noValidate className="mt-6 space-y-4">
          {serverError && <Alert variant="destructive" role="alert">{serverError}</Alert>}
          <Field id="code" label="Code from the SMS" error={codeForm.formState.errors.code?.message}>
            <Input id="code" inputMode="numeric" autoComplete="one-time-code" maxLength={6} placeholder="123456" invalid={!!codeForm.formState.errors.code} {...codeForm.register('code')} />
          </Field>
          <Field id="new_password" label="New password" hint="At least 8 characters" error={codeForm.formState.errors.new_password?.message}>
            <Input id="new_password" type="password" autoComplete="new-password" invalid={!!codeForm.formState.errors.new_password} {...codeForm.register('new_password')} />
          </Field>
          <Field id="confirm" label="New password again" error={codeForm.formState.errors.confirm?.message}>
            <Input id="confirm" type="password" autoComplete="new-password" invalid={!!codeForm.formState.errors.confirm} {...codeForm.register('confirm')} />
          </Field>
          <Button type="submit" className="w-full" size="lg" loading={codeForm.formState.isSubmitting}>Change password</Button>
        </form>
        <p className="mt-6 text-center text-sm text-muted-foreground">
          No SMS? <button type="button" className="font-medium text-primary underline-offset-4 hover:underline" onClick={() => { setPhone(null); setServerError(null) }}>Try again</button>
        </p>
      </div>
    )
  }

  return (
    <div>
      <h1 className="text-xl font-semibold">Forgot your password?</h1>
      <p className="mt-1 text-sm text-muted-foreground">Enter the phone number you registered with. We will send a code by SMS.</p>
      <form onSubmit={phoneForm.handleSubmit(requestCode)} noValidate className="mt-6 space-y-4">
        {serverError && <Alert variant="destructive" role="alert">{serverError}</Alert>}
        <Field id="phone" label="Phone number" error={phoneForm.formState.errors.phone?.message}>
          <Input id="phone" type="tel" inputMode="tel" autoComplete="tel" placeholder="0712 345 678" invalid={!!phoneForm.formState.errors.phone} {...phoneForm.register('phone')} />
        </Field>
        <Button type="submit" className="w-full" size="lg" loading={phoneForm.formState.isSubmitting}>Send me a code</Button>
      </form>
      <p className="mt-6 text-center text-sm text-muted-foreground">
        Remembered it? <Link to="/login" className="font-medium text-primary underline-offset-4 hover:underline">Sign in</Link>
      </p>
    </div>
  )
}
