import { request } from '@/lib/api'

export interface Conversation {
  id: string
  title: string | null
  created_at: string
  updated_at: string
}

export interface ToolCallRecord {
  name: string
  input: Record<string, unknown>
  ok: boolean
  duration_ms: number
}

export type ProposalKind = 'product' | 'sale' | 'repayment' | 'restock'
export type ProposalStatus = 'PENDING' | 'APPLIED' | 'REJECTED' | 'EXPIRED'

/** An action the copilot proposed. Nothing happens until the owner confirms it. */
export interface Proposal {
  kind: ProposalKind
  payload: Record<string, unknown>
  status: ProposalStatus
  entity_id: string | null
  applied_at: string | null
}

export interface AssistantMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  tool_calls: ToolCallRecord[] | null
  stop_reason: string | null
  created_at: string
  proposal?: Proposal | null
}

export interface ProposalResult {
  message: AssistantMessage
  kind: string
  entity_id: string | null
}

export interface ConversationDetail extends Conversation {
  messages: AssistantMessage[]
}

export interface Quota {
  daily_limit: number
  daily_used: number
  monthly_limit: number
  monthly_used: number
  resets_at: string
}

export interface AskResponse {
  conversation_id: string
  user_message: AssistantMessage
  assistant_message: AssistantMessage
  quota: Quota
}

export const MAX_QUESTION_CHARS = 2000

export const assistantApi = {
  quota: (signal?: AbortSignal) => request<Quota>('/api/v1/ai/quota', { signal }),
  listConversations: (signal?: AbortSignal) => request<Conversation[]>('/api/v1/ai/conversations', { signal }),
  getConversation: (id: string, signal?: AbortSignal) => request<ConversationDetail>(`/api/v1/ai/conversations/${id}`, { signal }),
  createConversation: () => request<Conversation>('/api/v1/ai/conversations', { method: 'POST', body: {} }),
  confirmProposal: (conversationId: string, messageId: string, payload: Record<string, unknown>) =>
    request<ProposalResult>(`/api/v1/ai/conversations/${conversationId}/messages/${messageId}/confirm`, { method: 'POST', body: { payload }, timeoutMs: 60_000 }),
  rejectProposal: (conversationId: string, messageId: string) =>
    request<ProposalResult>(`/api/v1/ai/conversations/${conversationId}/messages/${messageId}/reject`, { method: 'POST' }),
  ask: (conversationId: string, content: string) =>
    request<AskResponse>(`/api/v1/ai/conversations/${conversationId}/messages`, { method: 'POST', body: { content }, timeoutMs: 150_000 }),
}
