// @vitest-environment jsdom

import '@testing-library/jest-dom/vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, type ChatSubscription } from '../lib/api'
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
  },
}))

const chat = (captureMode: 'mentions' | 'full' = 'mentions'): ChatSubscription => ({
  id: 1,
  chat_id: -1001,
  title: 'Product chat',
  username: 'product_chat',
  chat_type: 'supergroup',
  capture_mode: captureMode,
  capture_mode_changed_at: '2026-08-20T12:00:00Z',
  subscribed_at: '2026-08-20T11:00:00Z',
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
    telegramMock.state.isTelegram = false
    telegramMock.state.initData = undefined
    telegramMock.state.backButton = undefined
    telegramMock.state.haptic = undefined
    vi.mocked(api.getChatMessages).mockResolvedValue([])
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
    vi.resetAllMocks()
  })

  it('shows the empty state when there are no subscriptions', async () => {
    vi.mocked(api.getChats).mockResolvedValue([])

    renderPage()

    expect(await screen.findByText(/Add the bot to a group/i)).toBeInTheDocument()
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
