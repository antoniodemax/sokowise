import { useQuery } from '@tanstack/react-query'

import { assistantApi } from './api'

export const assistantKeys = {
  all: ['assistant'] as const,
  quota: ['assistant', 'quota'] as const,
  conversations: ['assistant', 'conversations'] as const,
  conversation: (id: string) => ['assistant', 'conversation', id] as const,
}

export function useQuota() {
  return useQuery({ queryKey: assistantKeys.quota, queryFn: ({ signal }) => assistantApi.quota(signal) })
}

export function useConversations() {
  return useQuery({ queryKey: assistantKeys.conversations, queryFn: ({ signal }) => assistantApi.listConversations(signal) })
}

export function useConversation(id: string | null) {
  return useQuery({
    queryKey: assistantKeys.conversation(id ?? ''),
    queryFn: ({ signal }) => assistantApi.getConversation(id!, signal),
    enabled: !!id,
  })
}
