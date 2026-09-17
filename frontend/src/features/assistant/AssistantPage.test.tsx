import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { apiError, json, mockApi, renderWithProviders } from '@/test/render'

import AssistantPage from './AssistantPage'

const quota = { daily_limit: 10, daily_used: 3, monthly_limit: 100, monthly_used: 12, resets_at: '2026-09-17T21:00:00Z' }
const userMsg = { id: 'm1', role: 'user', content: 'How much did I make today?', tool_calls: null, stop_reason: null, created_at: '2026-09-17T08:00:00Z' }
const assistantMsg = {
  id: 'm2',
  role: 'assistant',
  content: 'Today you sold KSh 4,250 in 6 sales.\nCash collected was KSh 3,050; KSh 1,200 was on credit.',
  tool_calls: [{ name: 'get_business_summary', input: { period: 'today', date_from: null, date_to: null }, ok: true, duration_ms: 12 }],
  stop_reason: 'end_turn',
  created_at: '2026-09-17T08:00:04Z',
}

describe('AssistantPage', () => {
  it('shows the empty state with example questions and the quota, without inventing answers', async () => {
    const api = mockApi({ 'GET /api/v1/ai/quota': quota, 'GET /api/v1/ai/conversations': [] })
    renderWithProviders(<AssistantPage />, { path: '/assistant', pattern: '/assistant' })
    expect(await screen.findByRole('heading', { name: 'Ask about your business' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Who owes me money?' })).toBeInTheDocument()
    expect(await screen.findByText(/7 of 10 questions left today · 88 left this month/)).toBeInTheDocument()
    expect(screen.getByText('No conversations yet.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()
    expect(api.of('POST', '/api/v1/ai/conversations')).toHaveLength(0)
    expect(screen.queryByText(/KSh/)).not.toBeInTheDocument()
  })

  it('creates a conversation, sends the question, shows the loading state and renders the real answer', async () => {
    // The answer is released by the test, so the loading state is observable regardless of load.
    let answer!: (response: Response) => void
    const api = mockApi({
      'GET /api/v1/ai/quota': quota,
      'GET /api/v1/ai/conversations': [],
      'GET /api/v1/ai/conversations/c1': { id: 'c1', title: null, created_at: '', updated_at: '', messages: [] },
      'POST /api/v1/ai/conversations': () => json({ id: 'c1', title: null, created_at: '2026-09-17T08:00:00Z', updated_at: '2026-09-17T08:00:00Z' }, 201),
      'POST /api/v1/ai/conversations/c1/messages': () => new Promise<Response>((resolve) => { answer = resolve }),
    })
    renderWithProviders(<AssistantPage />, { path: '/assistant', pattern: '/assistant' })
    await userEvent.click(await screen.findByRole('button', { name: 'How much did I make today?' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Checking your records')
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()
    answer(json({ conversation_id: 'c1', user_message: userMsg, assistant_message: assistantMsg, quota: { ...quota, daily_used: 4 } }))
    expect(await screen.findByText(/Today you sold KSh 4,250/)).toBeInTheDocument()
    expect(screen.getByText(/Checked: business summary · figures come from your records/)).toBeInTheDocument()
    expect(screen.getByText(/6 of 10 questions left today/)).toBeInTheDocument()
    expect(api.of('POST', '/api/v1/ai/conversations')).toHaveLength(1)
    expect(api.of('POST', '/api/v1/ai/conversations/c1/messages')[0].body).toEqual({ content: 'How much did I make today?' })
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('sends a typed question with Enter and keeps Shift+Enter for a new line', async () => {
    const api = mockApi({
      'GET /api/v1/ai/quota': quota,
      'GET /api/v1/ai/conversations': [{ id: 'c1', title: 'Earlier', created_at: '', updated_at: '' }],
      'GET /api/v1/ai/conversations/c1': { id: 'c1', title: 'Earlier', created_at: '', updated_at: '', messages: [userMsg, assistantMsg] },
      'POST /api/v1/ai/conversations/c1/messages': () => json({ conversation_id: 'c1', user_message: { ...userMsg, id: 'm3', content: 'Who owes me?' }, assistant_message: { ...assistantMsg, id: 'm4', content: 'Mama Njeri owes KSh 500.', tool_calls: [{ name: 'get_debtors', input: {}, ok: true, duration_ms: 3 }] }, quota }),
    })
    renderWithProviders(<AssistantPage />, { path: '/assistant?c=c1', pattern: '/assistant' })
    expect(await screen.findByText(/Today you sold KSh 4,250/)).toBeInTheDocument()
    const box = screen.getByLabelText('Your question')
    await userEvent.type(box, 'Who owes{Shift>}{Enter}{/Shift} me?')
    expect(box).toHaveValue('Who owes\n me?')
    await userEvent.clear(box)
    await userEvent.type(box, 'Who owes me?{Enter}')
    expect(await screen.findByText('Mama Njeri owes KSh 500.')).toBeInTheDocument()
    expect(api.of('POST', '/api/v1/ai/conversations/c1/messages')[0].body).toEqual({ content: 'Who owes me?' })
    expect(api.of('POST', '/api/v1/ai/conversations')).toHaveLength(0)
    expect(screen.getByText(/Checked: customer debts/)).toBeInTheDocument()
    expect(within(screen.getByRole('complementary', { name: 'Conversations' })).getByRole('button', { name: 'Earlier' })).toHaveAttribute('aria-current', 'true')
  })

  it('shows a safe error with retry when the assistant is unavailable, and a quota message without retry', async () => {
    let attempts = 0
    const api = mockApi({
      'GET /api/v1/ai/quota': quota,
      'GET /api/v1/ai/conversations': [],
      'POST /api/v1/ai/conversations': () => json({ id: 'c1', title: null, created_at: '', updated_at: '' }, 201),
      'GET /api/v1/ai/conversations/c1': { id: 'c1', title: null, created_at: '', updated_at: '', messages: [] },
      'POST /api/v1/ai/conversations/c1/messages': () =>
        ++attempts === 1
          ? apiError(503, 'AI_TIMEOUT', 'The assistant took too long to answer. Please try again.')
          : apiError(429, 'AI_QUOTA_EXCEEDED', "You have used today's 10 questions. The limit resets at midnight.", { scope: 'day' }),
    })
    renderWithProviders(<AssistantPage />, { path: '/assistant', pattern: '/assistant' })
    await userEvent.type(await screen.findByLabelText('Your question'), 'How much today?{Enter}')
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('The assistant took too long to answer. Please try again. Your question was kept.')
    expect(screen.getByLabelText('Your question')).toHaveValue('How much today?')
    await userEvent.click(within(alert).getByRole('button', { name: 'Retry' }))
    await waitFor(() => expect(api.of('POST', '/api/v1/ai/conversations/c1/messages')).toHaveLength(2))
    expect(api.of('POST', '/api/v1/ai/conversations/c1/messages')[1].body).toEqual({ content: 'How much today?' })
    const quotaAlert = await screen.findByRole('alert')
    expect(quotaAlert).toHaveTextContent("You have used today's 10 questions")
    expect(within(quotaAlert).queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument()
  })

  it('disables asking when the quota is used up', async () => {
    mockApi({ 'GET /api/v1/ai/quota': { ...quota, daily_used: 10 }, 'GET /api/v1/ai/conversations': [] })
    renderWithProviders(<AssistantPage />, { path: '/assistant', pattern: '/assistant' })
    expect(await screen.findByText(/0 of 10 questions left today/)).toBeInTheDocument()
    expect(screen.getByLabelText('Your question')).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Who owes me money?' })).toBeDisabled()
  })

  it('offers a conversation picker for small screens', async () => {
    mockApi({ 'GET /api/v1/ai/quota': quota, 'GET /api/v1/ai/conversations': [{ id: 'c1', title: 'Earlier', created_at: '', updated_at: '' }] })
    renderWithProviders(<AssistantPage />, { path: '/assistant', pattern: '/assistant' })
    const picker = await screen.findByLabelText('Conversation')
    expect(await within(picker).findByRole('option', { name: 'Earlier' })).toBeInTheDocument()
  })
})
