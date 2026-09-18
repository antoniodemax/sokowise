import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Ban, ClipboardPaste, Link2, ShoppingCart, Smartphone, Wallet } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { toast } from 'sonner'

import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { EmptyState } from '@/components/ui/empty-state'
import { ErrorState } from '@/components/ui/error-state'
import { Input } from '@/components/ui/input'
import { PageHeader } from '@/components/ui/page-header'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { When } from '@/components/ui/when'
import { useAuth } from '@/features/auth/auth-context'
import { CustomerPicker } from '@/features/customers/CustomerPicker'
import { formatDateTime, localDate } from '@/lib/dates'
import { describeError } from '@/lib/errors'
import { formatKsh } from '@/lib/money'
import { queryKeys } from '@/lib/query-keys'

import { mpesaApi, type MpesaMessage } from './api'
import { useMpesaMessages, useMpesaReconciliation } from './hooks'

const STATUS: Record<MpesaMessage['status'], { label: string; variant: 'success' | 'warning' | 'neutral' | 'destructive' }> = {
  MATCHED: { label: 'Recorded', variant: 'success' },
  UNMATCHED: { label: 'Not recorded', variant: 'warning' },
  IGNORED: { label: 'Ignored', variant: 'neutral' },
  UNPARSED: { label: "Couldn't read", variant: 'destructive' },
}

/** The shared text lands in `text` (Android Messages) or, with some apps, in `title`. */
function sharedText(params: URLSearchParams): string {
  return (params.get('text') ?? params.get('title') ?? '').trim()
}

export default function MpesaPage() {
  const { session } = useAuth()
  const tz = session?.business.timezone ?? 'Africa/Nairobi'
  const isOwner = session?.role === 'OWNER'
  const queryClient = useQueryClient()
  const [params, setParams] = useSearchParams()
  const [text, setText] = useState(() => sharedText(params))
  const [day, setDay] = useState(() => localDate(new Date(), tz))
  const [repaying, setRepaying] = useState<MpesaMessage | null>(null)
  const [matching, setMatching] = useState<MpesaMessage | null>(null)

  const listParams = { date_from: day, date_to: day }
  const messages = useMpesaMessages(listParams)
  const summary = useMpesaReconciliation(day)

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.mpesa.all })
    void queryClient.invalidateQueries({ queryKey: queryKeys.customers.all })
    void queryClient.invalidateQueries({ queryKey: queryKeys.analytics.all })
  }

  const paste = useMutation({
    mutationFn: (value: string) => mpesaApi.paste(value),
    onSuccess: (message) => {
      setText('')
      if (params.has('text') || params.has('title')) setParams({}, { replace: true })
      if (message.status === 'MATCHED') toast.success('Already recorded: this payment is on a sale or a deni payment.')
      else if (message.status === 'UNPARSED') toast.error("Couldn't read that message. It is kept so you can check it.")
      else toast.success(`${formatKsh(message.amount)} received. Record it as a sale or a deni payment.`)
      if (message.occurred_at) setDay(localDate(new Date(message.occurred_at), tz))
      invalidate()
    },
  })
  const ignore = useMutation({
    mutationFn: (message: MpesaMessage) => mpesaApi.ignore(message.id),
    onSuccess: () => { toast.success('Message ignored'); invalidate() },
    onError: (error) => toast.error(describeError(error)),
  })

  return (
    <>
      <PageHeader title="M-Pesa" description="Money that came in on M-Pesa, and whether it is recorded here." />

      <Card className="mb-6">
        <CardHeader>
          <CardTitle>Add an M-Pesa message</CardTitle>
          <CardDescription>Copy the confirmation SMS and paste it here, or share it to SokoWise from your Messages app.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <Textarea id="mpesa-text" aria-label="M-Pesa message" rows={4} value={text} onChange={(e) => setText(e.target.value)} placeholder="RK1… Confirmed. You have received Ksh500.00 from …" />
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <Button onClick={() => paste.mutate(text.trim())} loading={paste.isPending} disabled={text.trim().length < 10}>
              <ClipboardPaste aria-hidden="true" /> Add message
            </Button>
            {paste.isError && <Alert variant="destructive" role="alert" className="flex-1">{describeError(paste.error)}</Alert>}
          </div>
        </CardContent>
      </Card>

      <div className="mb-4 flex flex-wrap items-end gap-3">
        <label className="grid gap-1 text-sm font-medium" htmlFor="mpesa-day">
          Day
          <Input id="mpesa-day" type="date" value={day} onChange={(e) => e.target.value && setDay(e.target.value)} className="w-44" />
        </label>
        {summary.data && (
          <dl className="grid flex-1 grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-4" aria-label="M-Pesa summary">
            <div><dt className="text-muted-foreground">Received</dt><dd className="font-semibold">{formatKsh(summary.data.received_total)} <span className="font-normal text-muted-foreground">· {summary.data.received_count} msg</span></dd></div>
            <div><dt className="text-muted-foreground">Recorded</dt><dd className="font-semibold">{formatKsh(summary.data.matched_total)}</dd></div>
            <div><dt className="text-muted-foreground">Not recorded</dt><dd className={`font-semibold ${summary.data.unmatched_count ? 'text-warning' : ''}`}>{formatKsh(summary.data.unmatched_total)} <span className="font-normal text-muted-foreground">· {summary.data.unmatched_count}</span></dd></div>
            <div><dt className="text-muted-foreground">In SokoWise</dt><dd className="font-semibold">{formatKsh(summary.data.recorded_in_app)}</dd></div>
          </dl>
        )}
      </div>

      {messages.isPending ? (
        <div className="space-y-2" aria-busy="true"><Skeleton className="h-16" /><Skeleton className="h-16" /></div>
      ) : messages.isError ? (
        <ErrorState error={messages.error} title="Could not load messages" onRetry={() => messages.refetch()} />
      ) : messages.data.length === 0 ? (
        <EmptyState icon={Smartphone} title="No M-Pesa messages for this day" description="Paste a confirmation SMS above and it will appear here." />
      ) : (
        <ul className="space-y-3">
          {[...messages.data].sort((a, b) => Number(b.status === 'UNMATCHED') - Number(a.status === 'UNMATCHED')).map((m) => (
            <li key={m.id}>
              <Card>
                <CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-lg font-semibold">{m.amount ? formatKsh(m.amount) : '—'}</span>
                      <Badge variant={STATUS[m.status].variant}>{STATUS[m.status].label}</Badge>
                      {m.kind && m.kind !== 'UNKNOWN' && <span className="text-xs text-muted-foreground">{m.kind === 'SEND_MONEY' ? 'Send money' : m.kind === 'POCHI' ? 'Pochi' : m.kind === 'TILL' ? 'Till' : 'Paybill'}</span>}
                    </div>
                    {m.status === 'UNPARSED' ? (
                      <p className="mt-1 text-sm text-muted-foreground">This did not look like an M-Pesa confirmation. Kept as pasted:</p>
                    ) : (
                      <p className="mt-1 text-sm text-muted-foreground">
                        {m.sender_name ?? 'Unknown sender'}{m.sender_phone_masked ? ` · ${m.sender_phone_masked}` : ''}{m.code ? ` · ${m.code}` : ''}
                      </p>
                    )}
                    {m.status === 'UNPARSED' && <pre className="mt-1 max-h-24 overflow-auto whitespace-pre-wrap rounded-md bg-muted p-2 text-xs">{m.raw_text}</pre>}
                    <p className="mt-1 text-xs text-muted-foreground">{m.occurred_at ? <When iso={m.occurred_at} timeZone={tz} /> : formatDateTime(m.created_at, tz)}</p>
                    {m.status === 'MATCHED' && m.sale_id && <Link to={`/sales/${m.sale_id}`} className="mt-1 inline-flex min-h-8 items-center text-sm text-primary hover:underline">View sale</Link>}
                    {m.status === 'MATCHED' && m.customer_id && <Link to={`/customers/${m.customer_id}`} className="mt-1 inline-flex min-h-8 items-center text-sm text-primary hover:underline">View customer</Link>}
                    {m.status === 'IGNORED' && m.ignore_reason && <p className="mt-1 text-xs text-muted-foreground">Reason: {m.ignore_reason}</p>}
                  </div>
                  {m.status === 'UNMATCHED' && (
                    <div className="grid grid-cols-2 gap-2 sm:flex sm:flex-wrap sm:justify-end">
                      <RecordSaleButton message={m} />
                      <Button variant="outline" onClick={() => setRepaying(m)}><Wallet aria-hidden="true" /> Deni payment</Button>
                      <Button variant="outline" onClick={() => setMatching(m)}><Link2 aria-hidden="true" /> Match sale</Button>
                      {isOwner && <Button variant="ghost" className="text-muted-foreground" onClick={() => ignore.mutate(m)} loading={ignore.isPending && ignore.variables?.id === m.id}><Ban aria-hidden="true" /> Ignore</Button>}
                    </div>
                  )}
                  {m.status === 'UNPARSED' && isOwner && (
                    <Button variant="ghost" className="text-muted-foreground" onClick={() => ignore.mutate(m)} loading={ignore.isPending && ignore.variables?.id === m.id}><Ban aria-hidden="true" /> Ignore</Button>
                  )}
                </CardContent>
              </Card>
            </li>
          ))}
        </ul>
      )}

      <RepaymentDialog message={repaying} onClose={() => setRepaying(null)} onDone={invalidate} />
      <MatchDialog message={matching} onClose={() => setMatching(null)} onDone={invalidate} timeZone={tz} />
    </>
  )
}

/** List rows are light; the dialogs load the row again to get its suggestions. */
function useCandidates(message: MpesaMessage | null) {
  return useQuery({
    queryKey: queryKeys.mpesa.detail(message?.id ?? ''),
    queryFn: ({ signal }) => mpesaApi.get(message!.id, signal),
    enabled: message !== null,
    staleTime: 0,
  })
}

function RecordSaleButton({ message }: { message: MpesaMessage }) {
  const navigate = useNavigate()
  const query = new URLSearchParams({ mpesa: message.id, amount: message.amount ?? '', code: message.code ?? '' })
  return (
    <Button onClick={() => navigate(`/sales/new?${query.toString()}`)}>
      <ShoppingCart aria-hidden="true" /> Record sale
    </Button>
  )
}

function RepaymentDialog({ message, onClose, onDone }: { message: MpesaMessage | null; onClose: () => void; onDone: () => void }) {
  const [error, setError] = useState<string | null>(null)
  const [overpay, setOverpay] = useState(false)
  const repay = useMutation({
    mutationFn: (customerId: string) => mpesaApi.repayment(message!.id, { customer_id: customerId, allow_overpayment: overpay }),
    onSuccess: () => { toast.success('Deni payment recorded'); setError(null); onDone(); onClose() },
    onError: (e) => setError(describeError(e)),
  })
  const detail = useCandidates(message)
  const candidates = detail.data?.candidates?.customers ?? []
  return (
    <Dialog open={message !== null} onOpenChange={(o) => { if (!o) { setError(null); onClose() } }}>
      <DialogContent aria-describedby="mpesa-repay-desc">
        <DialogHeader>
          <DialogTitle>Deni payment of {formatKsh(message?.amount)}</DialogTitle>
          <DialogDescription id="mpesa-repay-desc">Who paid? The amount and M-Pesa code come from the message.</DialogDescription>
        </DialogHeader>
        {detail.isPending && <Skeleton className="h-10" />}
        {candidates.length > 0 && (
          <div>
            <p className="mb-1 text-xs font-medium text-muted-foreground">Phone ends with {message?.sender_phone_masked?.slice(-3)}</p>
            <ul className="divide-y divide-border rounded-lg border border-border">
              {candidates.map((c) => (
                <li key={c.customer_id}>
                  <button type="button" onClick={() => repay.mutate(c.customer_id)} className="flex min-h-12 w-full items-center justify-between gap-3 px-3 py-2 text-left hover:bg-muted">
                    <span className="font-medium">{c.name}</span>
                    <span className="text-sm text-muted-foreground">owes {formatKsh(c.balance)}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
        <div>
          <p className="mb-1 text-xs font-medium text-muted-foreground">Or find the customer</p>
          <CustomerPicker onPick={(c) => repay.mutate(c.id)} />
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={overpay} onChange={(e) => setOverpay(e.target.checked)} /> Allow paying more than owed
        </label>
        {error && <Alert variant="destructive" role="alert">{error}</Alert>}
      </DialogContent>
    </Dialog>
  )
}

function MatchDialog({ message, onClose, onDone, timeZone }: { message: MpesaMessage | null; onClose: () => void; onDone: () => void; timeZone: string }) {
  const [error, setError] = useState<string | null>(null)
  const match = useMutation({
    mutationFn: (paymentId: string) => mpesaApi.match(message!.id, { payment_id: paymentId }),
    onSuccess: () => { toast.success('Matched to the sale'); setError(null); onDone(); onClose() },
    onError: (e) => setError(describeError(e)),
  })
  const detail = useCandidates(message)
  const candidates = detail.data?.candidates?.payments ?? []
  return (
    <Dialog open={message !== null} onOpenChange={(o) => { if (!o) { setError(null); onClose() } }}>
      <DialogContent aria-describedby="mpesa-match-desc">
        <DialogHeader>
          <DialogTitle>Which sale is this?</DialogTitle>
          <DialogDescription id="mpesa-match-desc">M-Pesa sales of {formatKsh(message?.amount)} recorded around the same time without a code.</DialogDescription>
        </DialogHeader>
        {detail.isPending ? (
          <Skeleton className="h-12" />
        ) : candidates.length === 0 ? (
          <p className="text-sm text-muted-foreground">No sale of this amount was recorded near that time. Use <strong>Record sale</strong> to add it.</p>
        ) : (
          <ul className="divide-y divide-border rounded-lg border border-border">
            {candidates.map((c) => (
              <li key={c.payment_id}>
                <button type="button" onClick={() => match.mutate(c.payment_id)} className="flex min-h-12 w-full items-center justify-between gap-3 px-3 py-2 text-left hover:bg-muted">
                  <span className="font-medium">{formatDateTime(c.sold_at, timeZone)}</span>
                  <span className="text-sm text-muted-foreground">{formatKsh(c.amount)}{c.reference ? ` · ${c.reference}` : ''}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
        {error && <Alert variant="destructive" role="alert">{error}</Alert>}
      </DialogContent>
    </Dialog>
  )
}
