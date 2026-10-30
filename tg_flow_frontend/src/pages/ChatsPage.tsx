import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../contexts/AuthContext'
import { useTelegram } from '../hooks/useTelegram'
import {
  api,
  type CaptureMode,
  type ChatMessage,
  type ChatSubscription,
} from '../lib/api'

function Message({ message }: { message: ChatMessage }) {
  const date = new Date(message.message_date)
  return (
    <article className="message-card">
      <div className="message-meta">
        <span>{message.from_username ? `@${message.from_username}` : `User ${message.from_user_id}`}</span>
        <span>{date.toLocaleString()}</span>
      </div>
      <p className="message-text">{message.text || '—'}</p>
    </article>
  )
}

export default function ChatsPage() {
  const { isAuthenticated } = useAuth()
  const { isTelegram, initData, backButton, haptic } = useTelegram()
  const queryClient = useQueryClient()
  const telegramInitData = isTelegram ? initData : undefined
  const [selectedChatId, setSelectedChatId] = useState<number | null>(null)
  const [modeError, setModeError] = useState<string | null>(null)

  useEffect(() => {
    if (!isTelegram || !backButton) return
    const goBack = () => window.history.back()
    backButton.show()
    backButton.onClick(goBack)
    return () => backButton.offClick(goBack)
  }, [backButton, isTelegram])

  const chatsQuery = useQuery<ChatSubscription[]>({
    queryKey: ['chats'],
    queryFn: () => api.getChats(telegramInitData),
    enabled: isAuthenticated,
  })

  const selectedChat = chatsQuery.data?.find((chat) => chat.chat_id === selectedChatId)
  const messagesQuery = useQuery<ChatMessage[]>({
    queryKey: ['chatMessages', selectedChatId],
    queryFn: () => api.getChatMessages(selectedChatId || 0, telegramInitData),
    enabled: isAuthenticated && selectedChat?.capture_mode === 'full',
    refetchInterval: selectedChat?.capture_mode === 'full' ? 15_000 : false,
  })

  const modeMutation = useMutation({
    mutationFn: ({ chatId, mode }: { chatId: number; mode: CaptureMode }) =>
      api.updateChatMode(chatId, mode, telegramInitData),
    onMutate: () => setModeError(null),
    onSuccess: (updated) => {
      queryClient.setQueryData<ChatSubscription[]>(['chats'], (current) =>
        current?.map((chat) => (chat.chat_id === updated.chat_id ? updated : chat)) || [updated]
      )
      queryClient.removeQueries({ queryKey: ['chatMessages', updated.chat_id] })
    },
    onError: () => setModeError('Couldn’t change the capture mode. Try again.'),
  })

  const selectMode = (chat: ChatSubscription, mode: CaptureMode) => {
    haptic?.impactOccurred('light')
    if (chat.capture_mode !== mode) modeMutation.mutate({ chatId: chat.chat_id, mode })
  }

  return (
    <div className="cosmos-page">
      <header className="topbar">
        <div className="topbar-inner">
          <Link to="/" className="back-link">← Home</Link>
          <Link className="brand" to="/"><span className="brand-mark" /><span>TG Flow</span></Link>
          <button className="refresh-button" onClick={() => chatsQuery.refetch()} aria-label="Refresh chats">↻</button>
        </div>
      </header>
      <main className="page-wrap capture-page">
        <div className="inbox-heading">
          <div><h1>Chats</h1></div>
          <p>Keep the focused mention inbox, or retain every new message in a chat.</p>
        </div>

        {chatsQuery.isLoading && <p className="lede">Loading chat subscriptions…</p>}
        {chatsQuery.error && <div className="error-box">Couldn’t load your chats.</div>}
        {modeError && <div className="error-box">{modeError}</div>}
        {!chatsQuery.isLoading && chatsQuery.data?.length === 0 && (
          <div className="panel capture-empty">Add the bot to a group and run <code>/subscribe</code>.</div>
        )}

        <div className="capture-grid">
          <section className="capture-list">
            {chatsQuery.data?.map((chat) => (
              <article key={chat.id} className={`panel capture-card${selectedChatId === chat.chat_id ? ' selected' : ''}`}>
                <button className="capture-card-heading" onClick={() => setSelectedChatId(chat.chat_id)}>
                  <span><strong>{chat.title || chat.username || `Chat ${chat.chat_id}`}</strong><small>{chat.username ? `@${chat.username}` : chat.chat_type}</small></span>
                  <span className={`mode-badge ${chat.capture_mode}`}>{chat.capture_mode === 'full' ? 'Full chat' : 'Mentions'}</span>
                </button>
                <div className="mode-switch" aria-label="Capture mode">
                  <button className={chat.capture_mode === 'mentions' ? 'active' : ''} onClick={() => selectMode(chat, 'mentions')} disabled={modeMutation.isPending}>Mentions + context</button>
                  <button className={chat.capture_mode === 'full' ? 'active' : ''} onClick={() => selectMode(chat, 'full')} disabled={modeMutation.isPending}>All messages</button>
                </div>
                <p className="mode-copy">{chat.capture_mode === 'full' ? 'Every new message is available in the complete feed from the moment this mode was enabled.' : 'Only mentions appear in your inbox, with five messages before and after.'}</p>
              </article>
            ))}
          </section>

          <section className="panel full-feed">
            {!selectedChat && <p className="feed-placeholder">Select a chat to inspect its capture mode.</p>}
            {selectedChat?.capture_mode === 'mentions' && <p className="feed-placeholder">This chat is in mention mode. Switch to “All messages” to start a complete feed.</p>}
            {selectedChat?.capture_mode === 'full' && (
              <>
                <div className="feed-heading"><div><p className="eyebrow">Live archive</p><h2>{selectedChat.title || `Chat ${selectedChat.chat_id}`}</h2></div><span>{messagesQuery.data?.length || 0} messages</span></div>
                {messagesQuery.isLoading && <p className="feed-placeholder">Loading messages…</p>}
                {messagesQuery.error && <div className="error-box">Couldn’t load the full feed.</div>}
                <div className="feed-messages">{messagesQuery.data?.map((message) => <Message key={message.id} message={message} />)}</div>
                {!messagesQuery.isLoading && messagesQuery.data?.length === 0 && <p className="feed-placeholder">New messages will appear here.</p>}
              </>
            )}
          </section>
        </div>
      </main>
    </div>
  )
}
