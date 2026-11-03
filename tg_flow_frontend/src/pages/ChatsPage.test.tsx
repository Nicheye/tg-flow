// @vitest-environment jsdom

import '@testing-library/jest-dom/vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, type CaptureMode, type ChatSubscription, type UnreadChatMessages } from '../lib/api'
import ChatsPage from './ChatsPage'

const telegramMock = vi.hoisted(() => ({
  state: {
    isTelegram: false,
    initData: undefined as string | undefined,
    backButton: undefined as
      | {
          show: ReturnType<typeof vi.fn>
          onClick: ReturnType<typeof vi.fn>
          offClick: ReturnType<typeof vi.fn>
        }
      | undefined,
    haptic: undefined as
      | { impactOccurred: ReturnType<typeof vi.fn> }
      | undefined,
  },
}))

vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({ isAuthenticated: true }),
}))

vi.mock('../hooks/useTelegram', () => ({
  useTelegram: () => telegramMock.state,
}))

vi.mock('../lib/api', () => ({
  api: {
    getChats: vi.fn(),
    updateChatMode: vi.fn(),
    getChatMessages: vi.fn(),
    getUnreadChatMessages: vi.fn(),
    markChatRead: vi.fn(),
    replyToChatMessage: vi.fn(),
    getChatReplyAttempt: vi.fn(),
  },
}))

const chat = (captureMode: CaptureMode = 'mentions'): ChatSubscription => ({
  id: 1,
  chat_id: -1001,
  title: 'Product chat',
  username: 'product_chat',
  chat_type: 'supergroup',
  source: 'group',
  connection_active: true,
  telegram_chat_id: null,
  capture_mode: captureMode,
  capture_mode_changed_at: '2026-08-20T12:00:00Z',
  subscribed_at: '2026-08-20T11:00:00Z',
  read_through_message_id: 0,
  last_read_at: null,
  unread_count: 0,
})

const businessChat = (captureMode: CaptureMode = 'full', connected = true): ChatSubscription => ({
  ...chat(captureMode),
  id: 2,
  chat_id: 21,
  title: 'Alice',
  username: 'alice',
  chat_type: 'private',
  source: 'business',
  connection_active: connected,
  telegram_chat_id: 987654321,
})

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const view = render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <ChatsPage />
      </MemoryRouter>
    </QueryClientProvider>
  )
  return { ...view, queryClient }
}

describe('ChatsPage', () => {
  beforeEach(() => {
    sessionStorage.clear()
    telegramMock.state.isTelegram = false
    telegramMock.state.initData = undefined
    telegramMock.state.backButton = undefined
    telegramMock.state.haptic = undefined
    vi.mocked(api.getUnreadChatMessages).mockResolvedValue({ messages: [], read_through_message_id: 0, snapshot_through_message_id: 0, capture_mode_changed_at: chat().capture_mode_changed_at, next_after_message_id: null, has_more: false, unread_count: 0 })
    vi.mocked(api.getChatMessages).mockResolvedValue([])
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
    vi.resetAllMocks()
  })

  it('replies to a selected Business message through explicit account send', async () => {
    vi.mocked(api.getChats).mockResolvedValue([businessChat()])
    vi.mocked(api.getChatMessages).mockResolvedValue([{ id: 7, chat_id: 21, message_id: 50, from_user_id: 99, from_username: 'alice', text: 'Synthetic question', message_date: '2026-11-03T12:05:00Z' }])
    vi.mocked(api.replyToChatMessage).mockResolvedValue({ status: 'sent', request_id: '123e4567-e89b-42d3-a456-426614174000', message_id: 51, reply_attached: true, error_code: null, error: null })
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /Alice.*Private chat/ }))
    fireEvent.click(await screen.findByRole('button', { name: 'Reply' }))
    expect(screen.getByRole('region', { name: 'Reply to Alice' })).toHaveTextContent('Synthetic question')
    fireEvent.change(screen.getByRole('textbox', { name: 'Your reply' }), { target: { value: 'Synthetic answer' } })
    expect(api.replyToChatMessage).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Send as me' }))
    await screen.findByText('Reply sent.')
    expect(api.replyToChatMessage).toHaveBeenCalledWith(21, 50, 'Synthetic answer', expect.any(String), undefined)
    expect(api.markChatRead).not.toHaveBeenCalled()
    await waitFor(() => expect(api.getChatMessages).toHaveBeenCalledTimes(2))
  })

  it.each([chat('full'), businessChat('full', false)])('does not offer sending for groups or disconnected accounts (%j)', async (subscription) => {
    vi.mocked(api.getChats).mockResolvedValue([subscription])
    vi.mocked(api.getChatMessages).mockResolvedValue([{ id: 7, chat_id: subscription.chat_id, message_id: 50, from_user_id: 99, from_username: 'sender', text: 'Synthetic message', message_date: '2026-11-03T12:05:00Z' }])
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: new RegExp(subscription.title!) }))
    await screen.findByText('Synthetic message')
    expect(screen.queryByRole('button', { name: 'Reply' })).not.toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: 'Your reply' })).not.toBeInTheDocument()
  })

  it('shows the empty state when there are no subscriptions', async () => {
    vi.mocked(api.getChats).mockResolvedValue([])

    renderPage()

    expect(await screen.findByText(/Add the bot to a group/i)).toBeInTheDocument()
    expect(screen.getByText(/person who adds it is automatically subscribed/i)).toBeInTheDocument()
    expect(screen.getByText(/remove and re-add the bot once/i)).toBeInTheDocument()
    expect(screen.queryByText('/subscribe')).not.toBeInTheDocument()
  })

  it('offers Business setup before any private chat exists without claiming a connection', async () => {
    vi.mocked(api.getChats).mockResolvedValue([])
    renderPage()
    const setup = await screen.findByText('Connect personal chats with Telegram Business')
    fireEvent.click(setup)
    const details = setup.closest('details')!
    expect(details).toHaveAttribute('open')
    expect(within(details).getByText(/enable Secretary Mode \(or Business Mode\)/)).toBeInTheDocument()
    expect(within(details).getByText(/choose the private conversations it may access/)).toBeInTheDocument()
    expect(within(details).getByText(/existing history is not imported/)).toBeInTheDocument()
    expect(within(details).getByText(/explicitly reply from your Telegram account with Send as me/)).toBeInTheDocument()
    expect(screen.queryByText(/Private chat · Telegram Business · Connected/)).not.toBeInTheDocument()
  })

  it('keeps mention mode for groups and offers only full capture for private chats', async () => {
    vi.mocked(api.getChats).mockResolvedValue([chat(), businessChat()])
    renderPage()
    const privateHeading = await screen.findByRole('button', { name: /Alice.*Private chat · Telegram Business · Connected/i })
    const privateCard = privateHeading.closest('article')!
    expect(within(privateCard).queryByRole('button', { name: 'Mentions + context' })).not.toBeInTheDocument()
    expect(within(privateCard).getByRole('button', { name: 'All messages' })).toHaveAttribute('aria-pressed', 'true')
    expect(within(privateCard).getByRole('button', { name: 'Disable subscription' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Mentions + context' })).toBeInTheDocument()
    fireEvent.click(privateHeading)
    await waitFor(() => expect(api.getChatMessages).toHaveBeenCalledWith(21, undefined))
    expect(api.getChatMessages).not.toHaveBeenCalledWith(987654321, undefined)
  })

  it('lets a connected private chat disable and explicitly resume capture', async () => {
    vi.mocked(api.getChats).mockResolvedValue([businessChat()])
    vi.mocked(api.updateChatMode).mockResolvedValueOnce(businessChat('disabled')).mockResolvedValueOnce(businessChat())
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Disable subscription' }))
    expect(await screen.findByText('Disabled')).toBeInTheDocument()
    expect(screen.getByText(/Saving is disabled for this private chat/)).toBeInTheDocument()
    expect(api.updateChatMode).toHaveBeenNthCalledWith(1, 21, 'disabled', undefined)
    fireEvent.click(screen.getByRole('button', { name: 'Re-enable · All messages' }))
    expect(await screen.findByText('Full chat')).toBeInTheDocument()
    expect(api.updateChatMode).toHaveBeenNthCalledWith(2, 21, 'full', undefined)
  })

  it('prevents re-enabling a disconnected private chat and explains how to reconnect', async () => {
    vi.mocked(api.getChats).mockResolvedValue([businessChat('disabled', false)])
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /Alice.*Private chat · Telegram Business · Disconnected/i }))
    expect(screen.getByRole('button', { name: 'All messages' })).toBeDisabled()
    const resume = screen.getByRole('button', { name: 'Re-enable · All messages' })
    expect(resume).toBeDisabled()
    fireEvent.click(resume)
    expect(api.updateChatMode).not.toHaveBeenCalled()
    expect(api.getChatMessages).not.toHaveBeenCalled()
    expect(screen.getByText(/Reconnect the bot in Telegram, then re-enable All messages/)).toBeInTheDocument()
  })

  it('preserves a disconnected private archive and checkpoint actions without polling for new messages', async () => {
    const initial = { ...businessChat('full', false), unread_count: 1 }
    const savedMessage = { id: 7, chat_id: 21, message_id: 50, from_user_id: 987654321, from_username: 'alice', text: 'Saved private message', message_date: '2026-08-20T12:05:00Z' }
    const updated = { ...initial, read_through_message_id: 50, unread_count: 0 }
    vi.mocked(api.getChats).mockResolvedValueOnce([initial]).mockResolvedValue([updated])
    vi.mocked(api.getChatMessages).mockResolvedValue([savedMessage])
    vi.mocked(api.getUnreadChatMessages).mockResolvedValueOnce({ messages: [savedMessage], read_through_message_id: 0, snapshot_through_message_id: 50, capture_mode_changed_at: initial.capture_mode_changed_at, next_after_message_id: null, has_more: false, unread_count: 1 }).mockResolvedValue({ messages: [], read_through_message_id: 50, snapshot_through_message_id: 50, capture_mode_changed_at: initial.capture_mode_changed_at, next_after_message_id: null, has_more: false, unread_count: 0 })
    vi.mocked(api.markChatRead).mockResolvedValue(updated)
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /Alice.*Private chat · Telegram Business · Disconnected/i }))
    expect(await screen.findAllByText('Saved private message')).toHaveLength(2)
    expect(screen.getByText(/Saved history is still available to you/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Disable subscription' })).toBeEnabled()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Mark as read' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: 'Mark as read' }))
    await waitFor(() => expect(api.markChatRead).toHaveBeenCalledWith(21, 50, initial.capture_mode_changed_at, undefined))
    await screen.findByText('0 unread', { selector: 'strong' })
    vi.useFakeTimers()
    try {
      await act(async () => { await vi.advanceTimersByTimeAsync(30_000) })
      expect(api.getChatMessages).toHaveBeenCalledOnce()
    } finally { vi.useRealTimers() }
  })


  it('keeps disabled subscriptions visible without fetching or polling their feed', async () => {
    vi.mocked(api.getChats).mockResolvedValue([chat('disabled')])
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /Product chat/i }))
    expect(screen.getByText('Disabled')).toBeInTheDocument()
    expect(screen.getByText(/messages sent while disabled are not backfilled/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'All messages' })).toHaveAttribute('aria-pressed', 'false')
    vi.useFakeTimers()
    try {
      await act(async () => { await vi.advanceTimersByTimeAsync(30_000) })
      expect(api.getChatMessages).not.toHaveBeenCalled()
    } finally { vi.useRealTimers() }
  })

  it('disables capture, drops its cached full feed and stops polling', async () => {
    vi.mocked(api.getChats).mockResolvedValue([chat('full')])
    vi.mocked(api.updateChatMode).mockResolvedValue(chat('disabled'))
    const { queryClient } = renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /Product chat/i }))
    await screen.findByText('New messages will appear here.')
    fireEvent.click(screen.getByRole('button', { name: 'Disable subscription' }))
    expect(await screen.findByText('Disabled')).toBeInTheDocument()
    expect(api.updateChatMode).toHaveBeenCalledWith(-1001, 'disabled', undefined)
    expect(queryClient.getQueryData(['chats'])).toEqual([chat('disabled')])
    expect(queryClient.getQueriesData({ queryKey: ['chatMessages', -1001] }).every(([, data]) => data === undefined)).toBe(true)
    const calls = vi.mocked(api.getChatMessages).mock.calls.length
    vi.useFakeTimers()
    try {
      await act(async () => { await vi.advanceTimersByTimeAsync(30_000) })
      expect(api.getChatMessages).toHaveBeenCalledTimes(calls)
    } finally { vi.useRealTimers() }
  })

  it('resumes a disabled subscription with an explicit All messages action', async () => {
    vi.mocked(api.getChats).mockResolvedValue([chat('disabled')])
    vi.mocked(api.updateChatMode).mockResolvedValue(chat('full'))
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /Product chat/i }))
    fireEvent.click(screen.getByRole('button', { name: 'Re-enable · All messages' }))
    expect(await screen.findByText('Full chat')).toBeInTheDocument()
    expect(api.updateChatMode).toHaveBeenCalledWith(-1001, 'full', undefined)
    await waitFor(() => expect(api.getChatMessages).toHaveBeenCalledOnce())
  })

  it('can resume a disabled subscription in mention mode instead', async () => {
    vi.mocked(api.getChats).mockResolvedValue([chat('disabled')])
    vi.mocked(api.updateChatMode).mockResolvedValue(chat('mentions'))
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Mentions + context' }))
    expect(await screen.findByText('Mentions')).toBeInTheDocument()
    expect(api.updateChatMode).toHaveBeenCalledWith(-1001, 'mentions', undefined)
    expect(api.getChatMessages).not.toHaveBeenCalled()
  })

  it('preserves a full subscription and its feed when disabling fails', async () => {
    vi.mocked(api.getChats).mockResolvedValue([chat('full')])
    vi.mocked(api.updateChatMode).mockRejectedValue(new Error('offline'))
    const { queryClient } = renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /Product chat/i }))
    await screen.findByText('New messages will appear here.')
    fireEvent.click(screen.getByRole('button', { name: 'Disable subscription' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Couldn’t change the capture mode')
    expect(screen.getByText('Full chat')).toBeInTheDocument()
    expect(queryClient.getQueryData(['chats'])).toEqual([chat('full')])
    expect(queryClient.getQueryData(['chatMessages', -1001, chat('full').capture_mode_changed_at])).toEqual([])
  })

  it('preserves disabled state when re-enabling fails', async () => {
    vi.mocked(api.getChats).mockResolvedValue([chat('disabled')])
    vi.mocked(api.updateChatMode).mockRejectedValue(new Error('offline'))
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Re-enable · All messages' }))
    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(screen.getByText('Disabled')).toBeInTheDocument()
    expect(api.getChatMessages).not.toHaveBeenCalled()
  })


  it('does not resurrect an in-flight full feed after disabling', async () => {
    let resolveFeed: ((messages: never[]) => void) | undefined
    vi.mocked(api.getChats).mockResolvedValue([chat('full')])
    vi.mocked(api.getChatMessages).mockImplementation(() => new Promise((resolve) => { resolveFeed = resolve }))
    vi.mocked(api.updateChatMode).mockResolvedValue(chat('disabled'))
    const { queryClient } = renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /Product chat/i }))
    await waitFor(() => expect(resolveFeed).toBeDefined())
    fireEvent.click(screen.getByRole('button', { name: 'Disable subscription' }))
    expect(await screen.findByText('Disabled')).toBeInTheDocument()
    await act(async () => resolveFeed?.([]))
    expect(queryClient.getQueriesData({ queryKey: ['chatMessages', -1001] }).every(([, data]) => data === undefined)).toBe(true)
    expect(screen.queryByText('New messages will appear here.')).not.toBeInTheDocument()
  })

  it('drops the old feed before resuming with the new capture boundary', async () => {
    vi.mocked(api.getChats).mockResolvedValue([chat('disabled')])
    const resumed = { ...chat('full'), capture_mode_changed_at: '2026-08-21T12:00:00Z' }
    vi.mocked(api.updateChatMode).mockResolvedValue(resumed)
    const { queryClient } = renderPage()
    queryClient.setQueryData(['chatMessages', -1001, chat('full').capture_mode_changed_at], [{ id: 9, text: 'Old feed' }])
    fireEvent.click(await screen.findByRole('button', { name: /Product chat/i }))
    fireEvent.click(screen.getByRole('button', { name: 'Re-enable · All messages' }))
    await screen.findByText('New messages will appear here.')
    expect(queryClient.getQueryData(['chatMessages', -1001, chat('full').capture_mode_changed_at])).toBeUndefined()
    expect(queryClient.getQueryData(['chatMessages', -1001, resumed.capture_mode_changed_at])).toEqual([])
    expect(screen.queryByText('Old feed')).not.toBeInTheDocument()
  })


  const unreadMessage = {
    id: 50, chat_id: -1001, message_id: 50, from_user_id: 9,
    from_username: 'alice', text: 'Unread snapshot message', message_date: '2026-08-20T12:05:00Z',
  }
  const unreadSnapshot = (): UnreadChatMessages => ({
    messages: [unreadMessage], read_through_message_id: 0,
    snapshot_through_message_id: 50, capture_mode_changed_at: chat().capture_mode_changed_at,
    next_after_message_id: null, has_more: false, unread_count: 1,
  })

  it('shows unread counts and never marks read just by opening a group', async () => {
    vi.mocked(api.getChats).mockResolvedValue([{ ...chat('full'), unread_count: 1 }])
    vi.mocked(api.getUnreadChatMessages).mockResolvedValue(unreadSnapshot())
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /Product chat/i }))
    expect(await screen.findByText(/snapshot through message #50/i)).toBeInTheDocument()
    expect(screen.getAllByText('1 unread')).toHaveLength(2)
    expect(screen.getByRole('button', { name: 'Mark as read' })).toBeEnabled()
    expect(api.markChatRead).not.toHaveBeenCalled()
    expect(api.getUnreadChatMessages).toHaveBeenCalledWith(-1001, chat().capture_mode_changed_at, undefined, expect.any(AbortSignal))
  })

  it('marks the observed boundary and preserves arrivals beyond it in refreshed counts', async () => {
    const updated = { ...chat('full'), read_through_message_id: 50, last_read_at: '2026-08-20T12:06:00Z', unread_count: 1 }
    vi.mocked(api.getChats).mockResolvedValueOnce([{ ...chat('full'), unread_count: 1 }]).mockResolvedValue([updated])
    vi.mocked(api.getUnreadChatMessages).mockResolvedValueOnce(unreadSnapshot()).mockResolvedValue({ ...unreadSnapshot(), messages: [{ ...unreadMessage, id: 51, message_id: 51, text: 'New arrival' }], read_through_message_id: 50, snapshot_through_message_id: 51 })
    vi.mocked(api.markChatRead).mockResolvedValue(updated)
    const { queryClient } = renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /Product chat/i }))
    await screen.findByText(/snapshot through message #50/i)
    fireEvent.click(screen.getByRole('button', { name: 'Mark as read' }))
    await waitFor(() => expect(api.markChatRead).toHaveBeenCalledWith(-1001, 50, chat().capture_mode_changed_at, undefined))
    expect(await screen.findByText(/snapshot through message #51/i)).toBeInTheDocument()
    expect(queryClient.getQueryData(['chats'])).toEqual([updated])
    expect(screen.getAllByText('1 unread')).toHaveLength(2)
    expect(queryClient.getQueryData(['chatUnread', -1001, chat().capture_mode_changed_at, 0])).toBeUndefined()
  })

  it('preserves cursor and observed snapshot when marking fails', async () => {
    const initial = { ...chat('full'), unread_count: 1 }
    vi.mocked(api.getChats).mockResolvedValue([initial])
    vi.mocked(api.getUnreadChatMessages).mockResolvedValue(unreadSnapshot())
    vi.mocked(api.markChatRead).mockRejectedValue(new Error('offline'))
    const { queryClient } = renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /Product chat/i }))
    await screen.findByText(/snapshot through message #50/i)
    fireEvent.click(screen.getByRole('button', { name: 'Mark as read' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Couldn’t confirm the update. Refresh unread to check your read position.')
    expect(queryClient.getQueryData(['chats'])).toEqual([initial])
    expect(screen.getByText(/snapshot through message #50/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Mark as read' })).toBeEnabled()
  })

  it('requires an available unread snapshot bound before marking', async () => {
    vi.mocked(api.getChats).mockResolvedValue([{ ...chat('full'), unread_count: 1 }])
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /Product chat/i }))
    await waitFor(() => expect(api.getUnreadChatMessages).toHaveBeenCalledOnce())
    expect(screen.getByRole('button', { name: 'Mark as read' })).toBeDisabled()
    expect(api.markChatRead).not.toHaveBeenCalled()
  })

  it('does not acknowledge an empty or obsolete snapshot generation', async () => {
    vi.mocked(api.getChats).mockResolvedValue([{ ...chat('full'), unread_count: 1 }])
    vi.mocked(api.getUnreadChatMessages).mockResolvedValue({ ...unreadSnapshot(), capture_mode_changed_at: '2026-08-19T12:00:00Z' })
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /Product chat/i }))
    await screen.findByText(/snapshot through message #50/i)
    expect(screen.getByRole('button', { name: 'Mark as read' })).toBeDisabled()
    expect(api.markChatRead).not.toHaveBeenCalled()
  })

  it('warns when marking includes snapshot messages outside the preview', async () => {
    vi.mocked(api.getChats).mockResolvedValue([{ ...chat('full'), unread_count: 201 }])
    vi.mocked(api.getUnreadChatMessages).mockResolvedValue({ ...unreadSnapshot(), has_more: true, snapshot_through_message_id: 250, unread_count: 201 })
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /Product chat/i }))
    expect(await screen.findByText(/including those not shown/i)).toHaveTextContent('#250')
    expect(screen.getByRole('button', { name: 'Mark as read' })).toBeEnabled()
  })

  it.each(['mentions', 'disabled'] as const)('never fetches unread or offers marking in %s mode', async (mode) => {
    vi.mocked(api.getChats).mockResolvedValue([chat(mode)])
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /Product chat/i }))
    expect(api.getUnreadChatMessages).not.toHaveBeenCalled()
    expect(screen.queryByRole('button', { name: 'Mark as read' })).not.toBeInTheDocument()
  })

  it('discards unread cache and late snapshot responses after changing mode', async () => {
    let resolveUnread: ((value: UnreadChatMessages) => void) | undefined
    vi.mocked(api.getChats).mockResolvedValue([{ ...chat('full'), unread_count: 1 }])
    vi.mocked(api.getUnreadChatMessages).mockImplementation(() => new Promise((resolve) => { resolveUnread = resolve }))
    vi.mocked(api.updateChatMode).mockResolvedValue(chat('disabled'))
    const { queryClient } = renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /Product chat/i }))
    await waitFor(() => expect(resolveUnread).toBeDefined())
    fireEvent.click(screen.getByRole('button', { name: 'Disable subscription' }))
    await screen.findByText('Disabled')
    await act(async () => resolveUnread?.(unreadSnapshot()))
    expect(queryClient.getQueriesData({ queryKey: ['chatUnread', -1001] }).every(([, data]) => data === undefined)).toBe(true)
    expect(screen.queryByRole('button', { name: 'Mark as read' })).not.toBeInTheDocument()
  })

  it('does not apply a previous chat snapshot when switching groups', async () => {
    let resolveUnread: ((value: UnreadChatMessages) => void) | undefined
    const second = { ...chat('full'), id: 2, chat_id: -1002, title: 'Other chat', unread_count: 1 }
    vi.mocked(api.getChats).mockResolvedValue([{ ...chat('full'), unread_count: 1 }, second])
    vi.mocked(api.getUnreadChatMessages).mockImplementationOnce(() => new Promise((resolve) => { resolveUnread = resolve })).mockResolvedValue({ ...unreadSnapshot(), snapshot_through_message_id: 80, messages: [{ ...unreadMessage, id: 80, message_id: 80, chat_id: -1002 }] })
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /Product chat/i }))
    await waitFor(() => expect(resolveUnread).toBeDefined())
    fireEvent.click(screen.getByRole('button', { name: /Other chat/i }))
    await screen.findByText(/snapshot through message #80/i)
    await act(async () => resolveUnread?.(unreadSnapshot()))
    vi.mocked(api.markChatRead).mockRejectedValue(new Error('test'))
    fireEvent.click(screen.getByRole('button', { name: 'Mark as read' }))
    await waitFor(() => expect(api.markChatRead).toHaveBeenCalledWith(-1002, 80, second.capture_mode_changed_at, undefined))
    expect(screen.queryByText(/snapshot through message #50/i)).not.toBeInTheDocument()
  })

  it('shows a load error', async () => {
    vi.mocked(api.getChats).mockRejectedValue(new Error('offline'))

    renderPage()

    expect(await screen.findByText(/Couldn’t load your chats/i)).toBeInTheDocument()
  })

  it('refreshes subscriptions on demand', async () => {
    vi.mocked(api.getChats).mockResolvedValue([])

    renderPage()
    await screen.findByText(/Add the bot to a group/i)
    fireEvent.click(screen.getByRole('button', { name: 'Refresh chats' }))

    await waitFor(() => expect(api.getChats).toHaveBeenCalledTimes(2))
  })

  it('switches a mention subscription to full mode', async () => {
    const mentionsChat = chat('mentions')
    const fullChat = chat('full')
    vi.mocked(api.getChats).mockResolvedValue([mentionsChat])
    vi.mocked(api.updateChatMode).mockResolvedValue(fullChat)

    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'All messages' }))

    await waitFor(() => {
      expect(api.updateChatMode).toHaveBeenCalledWith(-1001, 'full', undefined)
    })
    expect(await screen.findByText('Full chat')).toBeInTheDocument()
  })

  it('preserves other chat subscriptions when one mode changes', async () => {
    const first = chat('mentions')
    const second = { ...chat('full'), id: 2, chat_id: -1002, title: 'Other chat' }
    vi.mocked(api.getChats).mockResolvedValue([first, second])
    vi.mocked(api.updateChatMode).mockResolvedValue(chat('full'))

    renderPage()
    const allMessageButtons = await screen.findAllByRole('button', { name: 'All messages' })
    fireEvent.click(allMessageButtons[0])

    expect(await screen.findByText('Other chat')).toBeInTheDocument()
    await waitFor(() => expect(screen.getAllByText('Full chat')).toHaveLength(2))
  })

  it('restores the updated subscription if the cached list disappears mid-request', async () => {
    let resolveUpdate: ((value: ChatSubscription) => void) | undefined
    vi.mocked(api.getChats).mockResolvedValue([chat('mentions')])
    vi.mocked(api.updateChatMode).mockImplementation(
      () => new Promise((resolve) => { resolveUpdate = resolve })
    )

    const { queryClient } = renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'All messages' }))
    await waitFor(() => expect(resolveUpdate).toBeDefined())
    act(() => {
      queryClient.getQueryCache().find({ queryKey: ['chats'] })?.setData(undefined)
    })
    await act(async () => resolveUpdate?.(chat('full')))

    expect(await screen.findByText('Full chat')).toBeInTheDocument()
  })

  it('reports a mode-switch failure without changing the badge', async () => {
    vi.mocked(api.getChats).mockResolvedValue([chat('mentions')])
    vi.mocked(api.updateChatMode).mockRejectedValue(new Error('forbidden'))

    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'All messages' }))

    expect(await screen.findByText(/Couldn’t change the capture mode/i)).toBeInTheDocument()
    expect(screen.getByText('Mentions')).toBeInTheDocument()
  })

  it('does not submit the already active mode', async () => {
    vi.mocked(api.getChats).mockResolvedValue([chat('mentions')])

    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Mentions + context' }))

    expect(api.updateChatMode).not.toHaveBeenCalled()
  })

  it('switches a full subscription back to mention mode', async () => {
    const fullChat = chat('full')
    const mentionsChat = chat('mentions')
    vi.mocked(api.getChats).mockResolvedValue([fullChat])
    vi.mocked(api.updateChatMode).mockResolvedValue(mentionsChat)

    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Mentions + context' }))

    await waitFor(() => {
      expect(api.updateChatMode).toHaveBeenCalledWith(-1001, 'mentions', undefined)
    })
    expect(await screen.findByText('Mentions')).toBeInTheDocument()
  })

  it('explains that a selected mention-mode chat has no full feed', async () => {
    vi.mocked(api.getChats).mockResolvedValue([chat('mentions')])

    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /Product chat/i }))

    expect(await screen.findByText(/This chat is in mention mode/i)).toBeInTheDocument()
    expect(api.getChatMessages).not.toHaveBeenCalled()
  })

  it('loads and renders messages for a selected full chat', async () => {
    vi.mocked(api.getChats).mockResolvedValue([chat('full')])
    vi.mocked(api.getChatMessages).mockResolvedValue([
      {
        id: 5,
        chat_id: -1001,
        message_id: 50,
        from_user_id: 9,
        from_username: 'alice',
        text: 'Full-feed message',
        message_date: '2026-08-20T12:05:00Z',
      },
    ])

    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /Product chat/i }))

    expect(await screen.findByText('Full-feed message')).toBeInTheDocument()
    expect(api.getChatMessages).toHaveBeenCalledWith(-1001, undefined)
  })

  it('shows an error when the selected full feed cannot be loaded', async () => {
    vi.mocked(api.getChats).mockResolvedValue([chat('full')])
    vi.mocked(api.getChatMessages).mockRejectedValue(new Error('forbidden'))

    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /Product chat/i }))

    expect(await screen.findByText(/Couldn’t load the full feed/i)).toBeInTheDocument()
  })

  it('shows an empty full-feed state', async () => {
    vi.mocked(api.getChats).mockResolvedValue([chat('full')])
    vi.mocked(api.getChatMessages).mockResolvedValue([])

    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /Product chat/i }))

    expect(await screen.findByText(/New messages will appear here/i)).toBeInTheDocument()
  })

  it('renders fallback chat and sender labels for incomplete Telegram metadata', async () => {
    const fallbackChat = { ...chat('full'), chat_id: 0, title: null, username: null }
    vi.mocked(api.getChats).mockResolvedValue([fallbackChat])
    vi.mocked(api.getChatMessages).mockResolvedValue([
      {
        id: 6,
        chat_id: 0,
        message_id: 60,
        from_user_id: 9,
        from_username: null,
        text: null,
        message_date: '2026-08-20T12:05:00Z',
      },
    ])

    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /Chat 0/i }))

    expect(await screen.findByText('User 9')).toBeInTheDocument()
    expect(screen.getByText('—')).toBeInTheDocument()
    expect(api.getChatMessages).toHaveBeenCalledWith(0, undefined)
  })

  it('wires and cleans up the Telegram back button and haptics', async () => {
    const backButton = { show: vi.fn(), onClick: vi.fn(), offClick: vi.fn() }
    const haptic = { impactOccurred: vi.fn() }
    const historyBack = vi.spyOn(window.history, 'back').mockImplementation(() => undefined)
    telegramMock.state.isTelegram = true
    telegramMock.state.initData = 'signed-init-data'
    telegramMock.state.backButton = backButton
    telegramMock.state.haptic = haptic
    vi.mocked(api.getChats).mockResolvedValue([chat('mentions')])

    const view = renderPage()
    await screen.findByText('Product chat')
    fireEvent.click(screen.getByRole('button', { name: 'Mentions + context' }))

    expect(backButton.show).toHaveBeenCalledOnce()
    expect(backButton.onClick).toHaveBeenCalledOnce()
    backButton.onClick.mock.calls[0][0]()
    expect(historyBack).toHaveBeenCalledOnce()
    expect(haptic.impactOccurred).toHaveBeenCalledWith('light')
    view.unmount()
    expect(backButton.offClick).toHaveBeenCalledWith(backButton.onClick.mock.calls[0][0])
  })
})
