import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { KeyRound, MoreHorizontal, Plus, UserCheck, UserX } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'

import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { ErrorState } from '@/components/ui/error-state'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/features/auth/auth-context'
import { ApiError } from '@/lib/api'
import { formatDateTime } from '@/lib/dates'
import { describeError, fieldErrors } from '@/lib/errors'
import { queryKeys } from '@/lib/query-keys'

import { membersApi, type Member } from './api'

const password = z.string().min(8, 'At least 8 characters').max(128)
const staffSchema = z.object({ full_name: z.string().trim().min(2, "Enter the person's name").max(120), phone: z.string().trim().min(9, 'Enter a phone number').max(20), email: z.string().trim().email('Enter a valid email').or(z.literal('')), password })
type StaffValues = z.infer<typeof staffSchema>

function useMemberMutations() {
  const queryClient = useQueryClient()
  const invalidate = () => void queryClient.invalidateQueries({ queryKey: queryKeys.members.all })
  return { invalidate }
}

function AddStaffDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const { invalidate } = useMemberMutations()
  const [serverError, setServerError] = useState<string | null>(null)
  const form = useForm<StaffValues>({ resolver: zodResolver(staffSchema), defaultValues: { full_name: '', phone: '', email: '', password: '' } })
  const mutation = useMutation({
    mutationFn: (values: StaffValues) => membersApi.create({ full_name: values.full_name, phone: values.phone, email: values.email || null, password: values.password }),
    onSuccess: (member) => { invalidate(); toast.success(`${member.full_name} added. They must change the password when they first sign in.`); form.reset(); onOpenChange(false) },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409) { form.setError('phone', { message: error.message }); return }
      const perField = fieldErrors(error)
      let handled = false
      for (const [field, message] of Object.entries(perField)) if (field in form.getValues()) { form.setError(field as keyof StaffValues, { message }); handled = true }
      if (!handled) setServerError(describeError(error))
    },
  })
  const errors = form.formState.errors
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form onSubmit={form.handleSubmit((v) => { setServerError(null); mutation.mutate(v) })} noValidate className="space-y-4">
          <DialogHeader><DialogTitle>Add a staff member</DialogTitle><DialogDescription>They sign in with their phone number and the temporary password you set, then choose their own.</DialogDescription></DialogHeader>
          {serverError && <Alert variant="destructive">{serverError}</Alert>}
          <Field id="staff-name" label="Full name" error={errors.full_name?.message}><Input id="staff-name" autoFocus invalid={!!errors.full_name} {...form.register('full_name')} /></Field>
          <Field id="staff-phone" label="Phone" error={errors.phone?.message}><Input id="staff-phone" type="tel" inputMode="tel" invalid={!!errors.phone} {...form.register('phone')} /></Field>
          <Field id="staff-email" label="Email" optional error={errors.email?.message}><Input id="staff-email" type="email" invalid={!!errors.email} {...form.register('email')} /></Field>
          <Field id="staff-password" label="Temporary password" hint="Tell it to them in person; they will be asked to change it." error={errors.password?.message}><Input id="staff-password" type="text" autoComplete="off" invalid={!!errors.password} {...form.register('password')} /></Field>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={mutation.isPending}>Cancel</Button>
            <Button type="submit" loading={mutation.isPending}>Add staff</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function ResetPasswordDialog({ member, onOpenChange }: { member: Member | null; onOpenChange: (open: boolean) => void }) {
  const [value, setValue] = useState('')
  const [error, setError] = useState<string | null>(null)
  const mutation = useMutation({
    mutationFn: () => membersApi.resetPassword(member!.user_id, value),
    onSuccess: () => { toast.success(`Password reset for ${member?.full_name}. They must change it at next sign-in.`); setValue(''); onOpenChange(false) },
    onError: (e) => setError(fieldErrors(e).password ?? describeError(e)),
  })
  return (
    <Dialog open={member !== null} onOpenChange={(o) => { if (!mutation.isPending) { onOpenChange(o); setError(null); setValue('') } }}>
      <DialogContent>
        <form onSubmit={(e) => { e.preventDefault(); const parsed = password.safeParse(value); if (!parsed.success) { setError(parsed.error.issues[0].message); return } mutation.mutate() }} noValidate className="space-y-4">
          <DialogHeader><DialogTitle>Reset password for {member?.full_name}</DialogTitle><DialogDescription>Signs them out everywhere. They pick a new password when they next sign in.</DialogDescription></DialogHeader>
          <Field id="reset-password" label="Temporary password" error={error ?? undefined}><Input id="reset-password" type="text" autoComplete="off" autoFocus invalid={!!error} value={value} onChange={(e) => { setValue(e.target.value); setError(null) }} /></Field>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={mutation.isPending}>Cancel</Button>
            <Button type="submit" loading={mutation.isPending}>Reset password</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

export function TeamCard() {
  const { session } = useAuth()
  const { invalidate } = useMemberMutations()
  const members = useQuery({ queryKey: queryKeys.members.all, queryFn: ({ signal }) => membersApi.list(signal) })
  const [adding, setAdding] = useState(false)
  const [resetting, setResetting] = useState<Member | null>(null)
  const [confirm, setConfirm] = useState<{ member: Member; action: 'deactivate' | 'reactivate' | 'make_owner' | 'make_staff' } | null>(null)
  const update = useMutation({
    mutationFn: ({ member, action }: NonNullable<typeof confirm>) =>
      membersApi.update(member.user_id, action === 'deactivate' ? { is_active: false } : action === 'reactivate' ? { is_active: true } : { role: action === 'make_owner' ? 'OWNER' : 'STAFF' }),
    onSuccess: (member) => { invalidate(); toast.success(`${member.full_name} updated`) },
    onError: (error) => toast.error(describeError(error)),
  })
  const tz = session?.business.timezone ?? 'Africa/Nairobi'
  const labels = { deactivate: 'Deactivate', reactivate: 'Reactivate', make_owner: 'Make owner', make_staff: 'Make staff' }
  const descriptions = {
    deactivate: 'They are signed out everywhere and can no longer sign in. Their sales and records stay.',
    reactivate: 'They can sign in again with their existing password.',
    make_owner: 'Owners see all figures, expenses and analytics, and can void sales, change settings and manage staff.',
    make_staff: 'Staff can sell and manage customers and products, but cannot see profit, expenses or settings.',
  }

  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3">
        <div><CardTitle>Team</CardTitle><CardDescription>Who can sign in to {session?.business.name}.</CardDescription></div>
        <Button size="sm" onClick={() => setAdding(true)}><Plus aria-hidden="true" /> Add staff</Button>
      </CardHeader>
      <CardContent>
        {members.isPending ? (
          <div className="space-y-2" aria-busy="true"><Skeleton className="h-12" /><Skeleton className="h-12" /></div>
        ) : members.isError ? (
          <ErrorState error={members.error} title="Could not load the team" onRetry={() => members.refetch()} />
        ) : (
          <ul className="divide-y divide-border">
            {members.data.map((member) => {
              const me = member.user_id === session?.user.id
              return (
                <li key={member.user_id} className="flex items-center justify-between gap-3 py-3">
                  <div className="min-w-0">
                    <p className="flex flex-wrap items-center gap-2 text-sm font-medium">
                      <span className="truncate">{member.full_name}{me && <span className="text-muted-foreground"> (you)</span>}</span>
                      <Badge variant={member.role === 'OWNER' ? 'default' : 'neutral'}>{member.role === 'OWNER' ? 'Owner' : 'Staff'}</Badge>
                      {!member.is_active && <Badge variant="destructive">Deactivated</Badge>}
                      {member.is_active && member.must_change_password && <Badge variant="warning">Must change password</Badge>}
                    </p>
                    <p className="text-xs text-muted-foreground">{member.phone} · {member.last_login_at ? `last signed in ${formatDateTime(member.last_login_at, tz)}` : 'never signed in'}</p>
                  </div>
                  {!me && (
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild><Button variant="ghost" size="icon" aria-label={`Actions for ${member.full_name}`}><MoreHorizontal aria-hidden="true" /></Button></DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        {member.is_active && <DropdownMenuItem onSelect={() => setConfirm({ member, action: member.role === 'OWNER' ? 'make_staff' : 'make_owner' })}><UserCheck aria-hidden="true" /> {member.role === 'OWNER' ? 'Make staff' : 'Make owner'}</DropdownMenuItem>}
                        {member.is_active && <DropdownMenuItem onSelect={() => setResetting(member)}><KeyRound aria-hidden="true" /> Reset password</DropdownMenuItem>}
                        <DropdownMenuItem onSelect={() => setConfirm({ member, action: member.is_active ? 'deactivate' : 'reactivate' })} className={member.is_active ? 'text-destructive' : undefined}>{member.is_active ? <UserX aria-hidden="true" /> : <UserCheck aria-hidden="true" />} {member.is_active ? 'Deactivate' : 'Reactivate'}</DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </CardContent>
      <AddStaffDialog open={adding} onOpenChange={setAdding} />
      <ResetPasswordDialog member={resetting} onOpenChange={(o) => !o && setResetting(null)} />
      <ConfirmDialog open={confirm !== null} onOpenChange={(o) => !o && setConfirm(null)} title={confirm ? `${labels[confirm.action]} ${confirm.member.full_name}?` : ''} description={confirm ? descriptions[confirm.action] : undefined} confirmLabel={confirm ? labels[confirm.action] : 'Confirm'} destructive={confirm?.action === 'deactivate'} onConfirm={async () => { if (confirm) await update.mutateAsync(confirm) }} />
    </Card>
  )
}
