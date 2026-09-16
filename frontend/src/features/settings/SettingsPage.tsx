import { KeyRound } from 'lucide-react'
import { Link } from 'react-router'

import { Badge } from '@/components/ui/badge'
import { buttonVariants } from '@/components/ui/button-variants'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { PageHeader } from '@/components/ui/page-header'
import { useAuth } from '@/features/auth/auth-context'
import { cn } from '@/lib/utils'

export default function SettingsPage() {
  const { session } = useAuth()
  if (!session) return null
  const { user, business, role } = session
  return (
    <>
      <PageHeader title="Settings" description="Your account and business details." />
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Business</CardTitle>
            <CardDescription>Business settings will be editable here in the next phase.</CardDescription>
          </CardHeader>
          <CardContent>
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
              <dt className="text-muted-foreground">Name</dt>
              <dd className="font-medium">{business.name}</dd>
              <dt className="text-muted-foreground">Type</dt>
              <dd>{business.business_type.replaceAll('_', ' ').toLowerCase()}</dd>
              <dt className="text-muted-foreground">Currency</dt>
              <dd>{business.currency}</dd>
              <dt className="text-muted-foreground">Time zone</dt>
              <dd>{business.timezone}</dd>
            </dl>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center justify-between">
              Account <Badge variant={role === 'OWNER' ? 'default' : 'neutral'}>{role === 'OWNER' ? 'Owner' : 'Staff'}</Badge>
            </CardTitle>
            <CardDescription>Who you are signed in as.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
              <dt className="text-muted-foreground">Name</dt>
              <dd className="font-medium">{user.full_name}</dd>
              <dt className="text-muted-foreground">Phone</dt>
              <dd>{user.phone}</dd>
              <dt className="text-muted-foreground">Email</dt>
              <dd>{user.email ?? '—'}</dd>
            </dl>
            <Link to="/change-password" className={cn(buttonVariants({ variant: 'outline' }), 'w-full sm:w-auto')}>
              <KeyRound aria-hidden="true" /> Change password
            </Link>
          </CardContent>
        </Card>
      </div>
    </>
  )
}
