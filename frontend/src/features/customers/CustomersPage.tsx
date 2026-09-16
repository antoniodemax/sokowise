import { HandCoins, Plus, Search, Users } from 'lucide-react'
import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router'

import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { ErrorState } from '@/components/ui/error-state'
import { Input } from '@/components/ui/input'
import { PageHeader } from '@/components/ui/page-header'
import { Select } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useAuth } from '@/features/auth/auth-context'
import { formatDate } from '@/lib/dates'
import { formatKsh } from '@/lib/money'
import { useDebouncedValue } from '@/lib/use-debounce'
import { cn } from '@/lib/utils'

import { BalanceBadge } from './BalanceBadge'
import { CustomerFormDialog } from './CustomerFormDialog'
import { useCustomers, useDebtors } from './hooks'

export default function CustomersPage() {
  const { session } = useAuth()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const view = params.get('view') === 'debtors' ? 'debtors' : 'all'
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState<'balance' | 'age'>('balance')
  const [creating, setCreating] = useState(false)
  const debounced = useDebouncedValue(query.trim())
  const customers = useCustomers({ q: debounced || undefined, limit: 200 }, view === 'all')
  const debtors = useDebtors(sort, view === 'debtors')
  const tz = session?.business.timezone ?? 'Africa/Nairobi'

  const tabs = (
    <div role="tablist" aria-label="Customer views" className="flex rounded-lg border border-border bg-card p-1">
      {(['all', 'debtors'] as const).map((tab) => (
        <button key={tab} type="button" role="tab" aria-selected={view === tab} onClick={() => setParams(tab === 'all' ? {} : { view: 'debtors' }, { replace: true })} className={cn('min-h-11 flex-1 rounded-md px-3 text-sm font-medium sm:min-h-9 sm:flex-none', view === tab ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted')}>
          {tab === 'all' ? 'All customers' : 'Who owes you'}
        </button>
      ))}
    </div>
  )

  return (
    <>
      <PageHeader title="Customers" description="People you sell to, and what they owe." actions={<><Button onClick={() => setCreating(true)}><Plus aria-hidden="true" /> Add customer</Button></>} />
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center">
        {tabs}
        {view === 'all' ? (
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
            <Input aria-label="Search customers" placeholder="Search by name or phone" className="pl-9" value={query} onChange={(e) => setQuery(e.target.value)} />
          </div>
        ) : (
          <div className="w-full sm:w-56">
            <Select aria-label="Sort debtors" value={sort} onChange={(e) => setSort(e.target.value as 'balance' | 'age')}>
              <option value="balance">Largest debt first</option>
              <option value="age">Oldest debt first</option>
            </Select>
          </div>
        )}
      </div>

      {view === 'all' ? (
        customers.isPending ? (
          <div className="space-y-2" aria-busy="true"><Skeleton className="h-12" /><Skeleton className="h-12" /><Skeleton className="h-12" /></div>
        ) : customers.isError ? (
          <ErrorState error={customers.error} title="Could not load customers" onRetry={() => customers.refetch()} />
        ) : customers.data.length === 0 ? (
          <EmptyState icon={Users} title={debounced ? 'No customers match' : 'No customers yet'} description={debounced ? 'Try another name or phone number.' : 'Add customers to sell on credit and keep track of what they owe.'} action={!debounced ? <Button onClick={() => setCreating(true)}><Plus aria-hidden="true" /> Add your first customer</Button> : undefined} />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Customer</TableHead>
                <TableHead className="hidden sm:table-cell">Phone</TableHead>
                <TableHead className="text-right">Balance</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {customers.data.map((customer) => (
                <TableRow key={customer.id} className="cursor-pointer" onClick={() => navigate(`/customers/${customer.id}`)}>
                  <TableCell>
                    <button type="button" className="font-medium hover:underline" onClick={(e) => { e.stopPropagation(); navigate(`/customers/${customer.id}`) }}>{customer.name}</button>
                    <span className="block text-xs text-muted-foreground sm:hidden">{customer.phone ?? ''}</span>
                  </TableCell>
                  <TableCell className="hidden text-muted-foreground sm:table-cell">{customer.phone ?? '—'}</TableCell>
                  <TableCell className="text-right">{<BalanceBadge balance={customer.balance} />}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )
      ) : debtors.isPending ? (
        <div className="space-y-2" aria-busy="true"><Skeleton className="h-12" /><Skeleton className="h-12" /></div>
      ) : debtors.isError ? (
        <ErrorState error={debtors.error} title="Could not load debtors" onRetry={() => debtors.refetch()} />
      ) : debtors.data.length === 0 ? (
        <EmptyState icon={HandCoins} title="Nobody owes you money" description="Credit sales show up here until they are repaid." />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Customer</TableHead>
              <TableHead className="hidden sm:table-cell">Owing since</TableHead>
              <TableHead className="text-right">Owes</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {debtors.data.map((debtor) => (
              <TableRow key={debtor.customer_id} className="cursor-pointer" onClick={() => navigate(`/customers/${debtor.customer_id}`)}>
                <TableCell>
                  <button type="button" className="font-medium hover:underline" onClick={(e) => { e.stopPropagation(); navigate(`/customers/${debtor.customer_id}`) }}>{debtor.name}</button>
                  <span className="block text-xs text-muted-foreground">{debtor.phone ?? ''}</span>
                </TableCell>
                <TableCell className="hidden text-muted-foreground sm:table-cell">{formatDate(debtor.oldest_unpaid_charge_at, tz)}</TableCell>
                <TableCell className="tabular text-right font-semibold text-warning">{formatKsh(debtor.balance)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      <CustomerFormDialog open={creating} onOpenChange={setCreating} onSaved={(c) => navigate(`/customers/${c.id}`)} />
    </>
  )
}
