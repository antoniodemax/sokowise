import { useQuery } from '@tanstack/react-query'
import { KeyRound, Pencil } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { buttonVariants } from '@/components/ui/button-variants'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { ErrorState } from '@/components/ui/error-state'
import { PageHeader } from '@/components/ui/page-header'
import { Skeleton } from '@/components/ui/skeleton'
import { BUSINESS_TYPES } from '@/features/auth/api'
import { useAuth } from '@/features/auth/auth-context'
import { queryKeys } from '@/lib/query-keys'
import { cn } from '@/lib/utils'

import { businessApi } from './api'
import { BusinessForm } from './BusinessForm'
import { TeamCard } from './TeamCard'

function typeLabel(value: string) {
  return BUSINESS_TYPES.find((t) => t.value === value)?.label ?? value.replaceAll('_', ' ').toLowerCase()
}

export default function SettingsPage() {
  const { session } = useAuth()
  const isOwner = session?.role === 'OWNER'
  const [editing, setEditing] = useState(false)
  const business = useQuery({ queryKey: queryKeys.business.all, queryFn: ({ signal }) => businessApi.get(signal), enabled: isOwner })
  if (!session) return null
  const { user, role } = session

  return (
    <>
      <PageHeader title="Settings" description="Your account and business details." />
      <div className="grid gap-4 md:grid-cols-2">
        <Card className={isOwner ? 'md:col-span-2' : undefined}>
          <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3">
            <div><CardTitle>Business</CardTitle><CardDescription>{isOwner ? 'Details and how the shop runs.' : 'Only the owner can change these.'}</CardDescription></div>
            {isOwner && !editing && business.data && <Button size="sm" variant="outline" onClick={() => setEditing(true)}><Pencil aria-hidden="true" /> Edit</Button>}
          </CardHeader>
          <CardContent>
            {!isOwner ? (
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
                <dt className="text-muted-foreground">Name</dt><dd className="font-medium">{session.business.name}</dd>
                <dt className="text-muted-foreground">Type</dt><dd>{typeLabel(session.business.business_type)}</dd>
                <dt className="text-muted-foreground">Currency</dt><dd>{session.business.currency}</dd>
                <dt className="text-muted-foreground">Time zone</dt><dd>{session.business.timezone}</dd>
              </dl>
            ) : business.isPending ? (
              <div className="space-y-2" aria-busy="true"><Skeleton className="h-5 w-48" /><Skeleton className="h-5 w-64" /><Skeleton className="h-5 w-40" /></div>
            ) : business.isError ? (
              <ErrorState error={business.error} title="Could not load business details" onRetry={() => business.refetch()} />
            ) : editing ? (
              <BusinessForm business={business.data} onDone={() => setEditing(false)} />
            ) : (
              <dl className="grid gap-x-4 gap-y-2 text-sm sm:grid-cols-[auto_1fr]">
                <dt className="text-muted-foreground">Name</dt><dd className="font-medium">{business.data.name}</dd>
                <dt className="text-muted-foreground">Type</dt><dd>{typeLabel(business.data.business_type)}</dd>
                <dt className="text-muted-foreground">Phone</dt><dd>{business.data.phone ?? '—'}</dd>
                <dt className="text-muted-foreground">Address</dt><dd>{business.data.address ?? '—'}</dd>
                <dt className="text-muted-foreground">Currency</dt><dd>{business.data.currency}</dd>
                <dt className="text-muted-foreground">Time zone</dt><dd>{business.data.timezone}</dd>
                <dt className="text-muted-foreground">Staff can restock</dt><dd>{business.data.settings.staff_can_restock ? 'Yes' : 'No — owner only'}</dd>
                <dt className="text-muted-foreground">Backdate sales</dt><dd>{business.data.settings.sale_backdate_days ? `Up to ${business.data.settings.sale_backdate_days} ${business.data.settings.sale_backdate_days === 1 ? 'day' : 'days'}` : 'Today only'}</dd>
                <dt className="text-muted-foreground">Default low-stock alert</dt><dd>{business.data.settings.low_stock_default_threshold ?? 0}</dd>
              </dl>
            )}
          </CardContent>
        </Card>
        {isOwner && <div className="md:col-span-2"><TeamCard /></div>}
        <Card className={isOwner ? 'md:col-span-2' : undefined}>
          <CardHeader>
            <CardTitle className="flex items-center justify-between">Account <Badge variant={role === 'OWNER' ? 'default' : 'neutral'}>{role === 'OWNER' ? 'Owner' : 'Staff'}</Badge></CardTitle>
            <CardDescription>Who you are signed in as.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
              <dt className="text-muted-foreground">Name</dt><dd className="font-medium">{user.full_name}</dd>
              <dt className="text-muted-foreground">Phone</dt><dd>{user.phone}</dd>
              <dt className="text-muted-foreground">Email</dt><dd>{user.email ?? '—'}</dd>
            </dl>
            <Link to="/change-password" className={cn(buttonVariants({ variant: 'outline' }), 'w-full sm:w-auto')}><KeyRound aria-hidden="true" /> Change password</Link>
          </CardContent>
        </Card>
      </div>
    </>
  )
}
