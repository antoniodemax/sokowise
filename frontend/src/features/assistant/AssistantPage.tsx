import { useMutation, useQueryClient } from '@tanstack/react-query'
import { MessageSquarePlus, SendHorizontal, Sparkles } from 'lucide-react'
import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { useSearchParams } from 'react-router'

import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { PageHeader } from '@/components/ui/page-header'
import { Select } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Spinner } from '@/components/ui/spinner'
import { Textarea } from '@/components/ui/textarea'
import { useAuth } from '@/features/auth/auth-context'
import { ApiError } from '@/lib/api'
import { formatDateTime } from '@/lib/dates'
import { describeError } from '@/lib/errors'
import { cn } from '@/lib/utils'

import { assistantApi, MAX_QUESTION_CHARS, type AskResponse, type AssistantMessage, type ConversationDetail } from './api'
import { EXAMPLE_QUESTIONS } from './examples'
import { assistantKeys, useConversation, useConversations, useQuota } from './hooks'

const TOOL_LABELS: Record<string, string> = {
  get_business_summary: 'business summary',
  get_sales_summary: 'sales',
  get_product_performance: 'product performance',
  get_slow_products: 'slow products',
  get_inventory_status: 'stock levels',
  get_debtors: 'customer debts',
  get_expense_summary: 'expenses',
  search_customers: 'customer search',
}

/** AI errors carry a safe, specific message from the backend; other errors use the usual copy. */
function describeAskError(error: unknown): string {
  return error instanceof ApiError && error.code.startsWith('AI_') ? error.message : describeError(error)
}

function MessageBubble({ message, timezone }: { message: AssistantMessage; timezone: string }) {
  const mine = message.role === 'user'
  const checked = [...new Set((message.tool_calls ?? []).filter((c) => c.ok).map((c) => TOOL_LABELS[c.name] ?? c.name))]
  return (
    <li className={cn('flex gap-3', mine && 'justify-end')}>
      {!mine && (
        <span className="mt-1 flex size-8 shrink-0 items-center justify-center rounded-full bg-primary-soft text-primary" aria-hidden="true">
          <Sparkles className="size-4" />
        </span>
      )}
      <div className={cn('max-w-[85%] rounded-2xl px-4 py-3 text-sm', mine ? 'bg-primary text-primary-foreground' : 'border border-border bg-card')}>
        <p className="sr-only">{mine ? 'You' : 'Copilot'}:</p>
        <p className="whitespace-pre-wrap">{message.content}</p>
        {!mine && message.stop_reason === 'max_tokens' && <p className="mt-2 text-xs text-warning">This answer was cut short. Ask a narrower question for the rest.</p>}
        {!mine && checked.length > 0 && <p className="mt-2 text-xs text-muted-foreground">Checked: {checked.join(', ')} · figures come from your records</p>}
        <p className="mt-1 text-[11px] opacity-70">{formatDateTime(message.created_at, timezone)}</p>
      </div>
    </li>
  )
}

export default function AssistantPage() {
  const { session } = useAuth()
  const tz = session?.business.timezone ?? 'Africa/Nairobi'
  const queryClient = useQueryClient()
  const [params, setParams] = useSearchParams()
  const conversationId = params.get('c')
  const conversations = useConversations()
  const conversation = useConversation(conversationId)
  const quota = useQuota()
  const [draft, setDraft] = useState('')
  const [pending, setPending] = useState<string | null>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const focusInput = () => document.getElementById('question')?.focus()

  const messages = conversation.data?.messages ?? []
  useEffect(() => {
    const list = listRef.current
    if (list && typeof list.scrollTo === 'function') list.scrollTo({ top: list.scrollHeight })
  }, [messages.length, pending])

  const ask = useMutation({
    mutationFn: async (content: string): Promise<AskResponse> => {
      const id = conversationId ?? (await assistantApi.createConversation()).id
      if (id !== conversationId) setParams({ c: id }, { replace: true })
      return assistantApi.ask(id, content)
    },
    onMutate: (content) => setPending(content),
    onSuccess: async (result) => {
      setPending(null)
      setDraft('')
      // A GET for a freshly created conversation may still be in flight; drop it so its
      // empty message list cannot overwrite the answer written below.
      await queryClient.cancelQueries({ queryKey: assistantKeys.conversation(result.conversation_id) })
      queryClient.setQueryData<ConversationDetail>(assistantKeys.conversation(result.conversation_id), (current) => ({
        id: result.conversation_id,
        title: current?.title ?? result.user_message.content.slice(0, 120),
        created_at: current?.created_at ?? result.user_message.created_at,
        updated_at: result.assistant_message.created_at,
        messages: [...(current?.messages ?? []), result.user_message, result.assistant_message],
      }))
      queryClient.setQueryData(assistantKeys.quota, result.quota)
      void queryClient.invalidateQueries({ queryKey: assistantKeys.conversations })
      focusInput()
    },
    onError: () => {
      // The question stays in the box; the backend kept it too, so a retry does not double-count.
      void queryClient.invalidateQueries({ queryKey: assistantKeys.quota })
    },
  })

  const quotaExhausted = quota.data ? quota.data.daily_used >= quota.data.daily_limit || quota.data.monthly_used >= quota.data.monthly_limit : false
  const canSend = draft.trim().length > 0 && draft.length <= MAX_QUESTION_CHARS && !ask.isPending && !quotaExhausted

  const send = (text = draft) => {
    const content = text.trim()
    if (!content || ask.isPending) return
    setDraft(content)
    ask.mutate(content)
  }

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      if (canSend) send()
    }
  }

  const startNew = () => {
    setParams({}, { replace: true })
    setPending(null)
    ask.reset()
    focusInput()
  }

  const quotaLine = quota.data
    ? `${Math.max(0, quota.data.daily_limit - quota.data.daily_used)} of ${quota.data.daily_limit} questions left today · ${Math.max(0, quota.data.monthly_limit - quota.data.monthly_used)} left this month`
    : null

  return (
    <>
      <PageHeader
        title="Copilot"
        description="Ask about your sales, stock, customers, debts and expenses. Answers come from your own records."
        actions={<Button variant="outline" onClick={startNew} disabled={!conversationId && messages.length === 0 && !pending}><MessageSquarePlus aria-hidden="true" /> New conversation</Button>}
      />
      <div className="grid gap-4 lg:grid-cols-[16rem_1fr]">
        <aside aria-label="Conversations" className="lg:rounded-xl lg:border lg:border-border lg:bg-card lg:p-3">
          <div className="lg:hidden">
            <label htmlFor="conversation-select" className="sr-only">Conversation</label>
            <Select id="conversation-select" value={conversationId ?? ''} onChange={(e) => (e.target.value ? setParams({ c: e.target.value }, { replace: true }) : startNew())}>
              <option value="">New conversation</option>
              {(conversations.data ?? []).map((c) => <option key={c.id} value={c.id}>{c.title ?? 'Untitled'}</option>)}
            </Select>
          </div>
          <ul className="hidden max-h-[60vh] space-y-1 overflow-y-auto lg:block">
            {conversations.isPending && <li><Skeleton className="h-9" /></li>}
            {conversations.isError && <li className="px-2 py-2 text-sm text-muted-foreground">{describeAskError(conversations.error)}</li>}
            {conversations.data?.length === 0 && <li className="px-2 py-2 text-sm text-muted-foreground">No conversations yet.</li>}
            {(conversations.data ?? []).map((c) => (
              <li key={c.id}>
                <button type="button" aria-current={c.id === conversationId ? 'true' : undefined} onClick={() => setParams({ c: c.id }, { replace: true })} className={cn('block w-full truncate rounded-md px-2 py-2 text-left text-sm hover:bg-muted', c.id === conversationId && 'bg-primary-soft font-medium text-primary')}>
                  {c.title ?? 'Untitled'}
                </button>
              </li>
            ))}
          </ul>
        </aside>

        <section aria-label="Chat" className="flex min-h-[60vh] flex-col rounded-xl border border-border bg-background">
          <div ref={listRef} className="flex-1 overflow-y-auto p-4">
            {conversationId && conversation.isPending ? (
              <div className="space-y-3" aria-busy="true"><Skeleton className="h-12 w-2/3" /><Skeleton className="ml-auto h-10 w-1/2" /></div>
            ) : conversation.isError ? (
              <Alert variant="destructive">{describeError(conversation.error)}</Alert>
            ) : messages.length === 0 && !pending ? (
              <div className="mx-auto max-w-xl py-6 text-center">
                <span className="mx-auto flex size-12 items-center justify-center rounded-full bg-primary-soft text-primary" aria-hidden="true"><Sparkles className="size-6" /></span>
                <h2 className="mt-4 text-lg font-semibold">Ask about your business</h2>
                <p className="mt-1 text-sm text-muted-foreground">Try one of these, or type your own question in English or Swahili.</p>
                <ul className="mt-4 grid gap-2 sm:grid-cols-2">
                  {EXAMPLE_QUESTIONS.map((q) => (
                    <li key={q}>
                      <button type="button" onClick={() => send(q)} disabled={ask.isPending || quotaExhausted} className="w-full rounded-lg border border-border bg-card px-3 py-3 text-left text-sm hover:border-primary hover:bg-primary-soft disabled:opacity-50">
                        {q}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
              <ul className="space-y-4" aria-live="polite">
                {messages.map((m) => <MessageBubble key={m.id} message={m} timezone={tz} />)}
                {pending && (
                  <>
                    <li className="flex justify-end"><div className="max-w-[85%] rounded-2xl bg-primary px-4 py-3 text-sm text-primary-foreground opacity-80"><p className="sr-only">You:</p><p className="whitespace-pre-wrap">{pending}</p></div></li>
                    {ask.isPending && (
                      <li className="flex items-center gap-3 text-sm"><Spinner label="Checking your records…" /></li>
                    )}
                  </>
                )}
              </ul>
            )}
          </div>

          <div className="border-t border-border p-3">
            {ask.isError && (
              <Alert variant="destructive" className="mb-3" role="alert">
                <span className="flex-1">{describeAskError(ask.error)}{ask.error instanceof ApiError && ask.error.code === 'AI_QUOTA_EXCEEDED' ? '' : ' Your question was kept.'}</span>
                {!(ask.error instanceof ApiError && ask.error.code === 'AI_QUOTA_EXCEEDED') && <Button size="sm" variant="outline" onClick={() => send(pending ?? draft)}>Retry</Button>}
              </Alert>
            )}
            <form onSubmit={(e) => { e.preventDefault(); if (canSend) send() }} className="flex items-end gap-2">
              <div className="flex-1">
                <label htmlFor="question" className="sr-only">Your question</label>
                <Textarea id="question" rows={2} className="min-h-0 resize-none" maxLength={MAX_QUESTION_CHARS} placeholder={quotaExhausted ? 'You have used all your questions for now.' : 'Ask a question… (Enter to send, Shift+Enter for a new line)'} value={draft} disabled={ask.isPending || quotaExhausted} onChange={(e) => setDraft(e.target.value)} onKeyDown={onKeyDown} />
              </div>
              <Button type="submit" size="icon" aria-label="Send" disabled={!canSend} loading={ask.isPending}><SendHorizontal aria-hidden="true" /></Button>
            </form>
            <p className="mt-2 text-xs text-muted-foreground" aria-live="polite">
              {quota.isError ? describeAskError(quota.error) : quotaLine ?? 'Loading your question allowance…'} · The copilot reads your records; it cannot change them.
            </p>
          </div>
        </section>
      </div>
    </>
  )
}
