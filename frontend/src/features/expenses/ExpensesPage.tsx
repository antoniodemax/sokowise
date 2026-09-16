import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, Pencil, Plus, Receipt, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { EmptyState } from '@/components/ui/empty-state'
import { ErrorState } from '@/components/ui/error-state'
import { Input } from '@/components/ui/input'
import { PageHeader } from '@/components/ui/page-header'
import { Select } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useAuth } from '@/features/auth/auth-context'
import { formatDateTime, localDate } from '@/lib/dates'
import { fromCents, toCents } from '@/lib/decimal'
import { describeError } from '@/lib/errors'
import { formatKsh } from '@/lib/money'
import { queryKeys } from '@/lib/query-keys'

import { expensesApi, saveBlob, type Expense, type ExpenseListParams, type ExpenseMethod } from './api'
import { ExpenseFormDialog } from './ExpenseFormDialog'

export default function ExpensesPage() {
  const { session } = useAuth()
  const tz = session?.business.timezone ?? 'Africa/Nairobi'
  const queryClient = useQueryClient()
  const today = localDate(new Date(), tz)
  const [dateFrom, setDateFrom] = useState(`${today.slice(0, 8)}01`)
  const [dateTo, setDateTo] = useState(today)
  const [category, setCategory] = useState('')
  const [method, setMethod] = useState<'' | ExpenseMethod>('')
  const [includeDeleted, setIncludeDeleted] = useState(false)
  const [editing, setEditing] = useState<Expense | null | 'new'>(null)
  const [deleting, setDeleting] = useState<Expense | null>(null)

  const params: ExpenseListParams = { date_from: dateFrom || undefined, date_to: dateTo || undefined, category: category || undefined, payment_method: method || undefined, include_deleted: includeDeleted || undefined, limit: 200 }
  const expenses = useQuery({ queryKey: queryKeys.expenses.list(params), queryFn: ({ signal }) => expensesApi.list(params, signal) })
  const suggestions = useQuery({ queryKey: queryKeys.expenses.categories, queryFn: ({ signal }) => expensesApi.categories(signal), staleTime: 5 * 60_000 })
  const categories = [...new Set([...(suggestions.data?.suggested ?? []), ...(expenses.data ?? []).map((e) => e.category), category].filter(Boolean))].sort()

  const remove = useMutation({
    mutationFn: (expense: Expense) => expensesApi.remove(expense.id),
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: queryKeys.expenses.all }); void queryClient.invalidateQueries({ queryKey: queryKeys.analytics.all }); toast.success('Expense deleted') },
    onError: (error) => toast.error(describeError(error)),
  })
  const exportCsv = useMutation({
    mutationFn: () => expensesApi.exportCsv(params),
    onSuccess: (blob) => saveBlob(blob, `sokowise-expenses-${dateFrom || 'all'}-to-${dateTo || 'all'}.csv`),
    onError: (error) => toast.error(describeError(error)),
  })

  const live = (expenses.data ?? []).filter((e) => !e.deleted_at)
  const totalCents = live.reduce((sum, e) => sum + (toCents(e.amount) ?? 0), 0)

  return (
    <>
      <PageHeader title="Expenses" description="Running costs, so net profit is real." actions={<><Button variant="outline" onClick={() => exportCsv.mutate()} loading={exportCsv.isPending} disabled={!expenses.data?.length}><Download aria-hidden="true" /> Export CSV</Button><Button onClick={() => setEditing('new')}><Plus aria-hidden="true" /> Record expense</Button></>} />
      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-5">
        <div>
          <label htmlFor="exp-from" className="mb-1 block text-xs text-muted-foreground">From</label>
          <Input id="exp-from" type="date" value={dateFrom} max={dateTo || undefined} onChange={(e) => setDateFrom(e.target.value)} />
        </div>
        <div>
          <label htmlFor="exp-to" className="mb-1 block text-xs text-muted-foreground">To</label>
          <Input id="exp-to" type="date" value={dateTo} min={dateFrom || undefined} onChange={(e) => setDateTo(e.target.value)} />
        </div>
        <div>
          <label htmlFor="exp-category" className="mb-1 block text-xs text-muted-foreground">Category</label>
          <Select id="exp-category" value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="">All categories</option>
            {categories.map((c) => <option key={c} value={c}>{c}</option>)}
          </Select>
        </div>
        <div>
          <label htmlFor="exp-method" className="mb-1 block text-xs text-muted-foreground">Paid by</label>
          <Select id="exp-method" value={method} onChange={(e) => setMethod(e.target.value as '' | ExpenseMethod)}>
            <option value="">Cash and M-Pesa</option>
            <option value="CASH">Cash</option>
            <option value="MPESA">M-Pesa</option>
          </Select>
        </div>
        <label className="flex min-h-11 items-center gap-2 self-end text-sm">
          <Checkbox checked={includeDeleted} onChange={(e) => setIncludeDeleted(e.target.checked)} /> Show deleted
        </label>
      </div>
      {expenses.isPending ? (
        <div className="space-y-2" aria-busy="true"><Skeleton className="h-12" /><Skeleton className="h-12" /><Skeleton className="h-12" /></div>
      ) : expenses.isError ? (
        <ErrorState error={expenses.error} title="Could not load expenses" onRetry={() => expenses.refetch()} />
      ) : expenses.data.length === 0 ? (
        <EmptyState icon={Receipt} title="No expenses in this period" description="Record rent, transport, airtime and other running costs to see your true net profit." action={<Button onClick={() => setEditing('new')}><Plus aria-hidden="true" /> Record expense</Button>} />
      ) : (
        <>
          <p className="mb-2 text-sm text-muted-foreground" aria-live="polite">{live.length} {live.length === 1 ? 'expense' : 'expenses'} · total <span className="tabular font-semibold text-foreground">{formatKsh(fromCents(totalCents))}</span></p>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>When</TableHead>
                <TableHead>Category</TableHead>
                <TableHead className="hidden md:table-cell">Note</TableHead>
                <TableHead className="hidden sm:table-cell">Paid by</TableHead>
                <TableHead className="text-right">Amount</TableHead>
                <TableHead className="w-24"><span className="sr-only">Actions</span></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {expenses.data.map((expense) => {
                const deleted = !!expense.deleted_at
                return (
                  <TableRow key={expense.id} className={deleted ? 'opacity-60' : undefined}>
                    <TableCell className="whitespace-nowrap">{formatDateTime(expense.incurred_at, tz)}{deleted && <Badge variant="destructive" className="ml-2">Deleted</Badge>}</TableCell>
                    <TableCell className="font-medium">{expense.category}</TableCell>
                    <TableCell className="hidden max-w-64 truncate text-muted-foreground md:table-cell">{[expense.note, expense.reference].filter(Boolean).join(' · ') || '—'}</TableCell>
                    <TableCell className="hidden sm:table-cell">{expense.payment_method === 'MPESA' ? 'M-Pesa' : 'Cash'}</TableCell>
                    <TableCell className={`tabular text-right font-semibold ${deleted ? 'line-through' : ''}`}>{formatKsh(expense.amount)}</TableCell>
                    <TableCell className="text-right">
                      {!deleted && (
                        <span className="inline-flex">
                          <Button variant="ghost" size="icon" aria-label={`Edit ${expense.category} expense`} onClick={() => setEditing(expense)}><Pencil aria-hidden="true" /></Button>
                          <Button variant="ghost" size="icon" className="text-muted-foreground hover:text-destructive" aria-label={`Delete ${expense.category} expense`} onClick={() => setDeleting(expense)}><Trash2 aria-hidden="true" /></Button>
                        </span>
                      )}
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </>
      )}
      <ExpenseFormDialog open={editing !== null} onOpenChange={(o) => !o && setEditing(null)} expense={editing === 'new' ? null : editing} />
      <ConfirmDialog open={deleting !== null} onOpenChange={(o) => !o && setDeleting(null)} title="Delete this expense?" description={deleting ? `${formatKsh(deleting.amount)} for ${deleting.category}. It is kept in the records as deleted and no longer counts towards expenses.` : undefined} confirmLabel="Delete" destructive onConfirm={async () => { if (deleting) await remove.mutateAsync(deleting) }} />
    </>
  )
}
