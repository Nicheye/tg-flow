import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../contexts/AuthContext'
import { useTelegram } from '../hooks/useTelegram'
import BusinessReplyComposer from '../components/BusinessReplyComposer'
import {
  api,
  type CaptureMode,
  type ChatMessage,
  type ChatSubscription,
  type UnreadChatMessages,
} from '../lib/api'

function Message({ message, onReply }: { message: ChatMessage; onReply?: () => void }) {
  const date = new Date(message.message_date)
  return (
    <article className="message-card">
      <div className="message-meta">
        <span>{message.from_username ? `@${message.from_username}` : `User ${message.from_user_id}`}</span>
        <span>{date.toLocaleString()}</span>
      </div>
      <p className="message-text">{message.text || '—'}</p>
      {onReply && <button type="button" className="secondary-button message-reply-button" onClick={onReply}>Reply</button>}
    </article>
  )
}

function isBusinessDisconnected(chat: ChatSubscription) {
  return chat.source === 'business' && !chat.connection_active
}

function captureDescription(chat: ChatSubscription) {
  if (isBusinessDisconnected(chat)) {
    return 'Telegram Business is disconnected. New messages are not being saved. Reconnect this bot in your Telegram account settings to resume capture.'
  }
  if (chat.capture_mode === 'disabled') {
    return chat.source === 'business'
      ? 'Saving is disabled for this private chat. Re-enable All messages to collect new messages.'
      : 'Your subscription is disabled. New messages and mentions are not collected for you. Choose a mode above or re-enable with All messages.'
  }
  return chat.capture_mode === 'full'
    ? 'Every new message is available in the complete feed from the moment this mode was enabled.'
    : 'Only mentions appear in your inbox, with five messages before and after.'
}

function BusinessSetup() {
  const botUsername = import.meta.env.VITE_BOT_USERNAME?.replace(/^@/, '')
  const botName = botUsername && botUsername !== 'your_bot' && botUsername !== 'your_bot_username'
    ? `@${botUsername}` : 'your TG Flow bot'

  return (
    <details className="panel business-setup">
      <summary>Connect personal chats with Telegram Business</summary>
      <div className="business-setup-content">
        <ol>
          <li>As the bot owner, enable Secretary Mode (or Business Mode) for {botName} in <a href="https://t.me/BotFather" target="_blank" rel="noreferrer">@BotFather</a>.</li>
          <li>In your Telegram account settings, open the connected bots or chat automation settings, connect {botName}, and choose the private conversations it may access. The setting name depends on your Telegram version.</li>
          <li>Send or receive a new message in an allowed conversation, then refresh this page. The private chat appears here with All messages enabled.</li>
        </ol>
        <p>Only new messages delivered after connection are collected; existing history is not imported. This connection covers personal chats. Groups continue to use the bot added to the group.</p>
        <p>Use Disable subscription to stop saving a chat, or disconnect the bot in Telegram to stop the connection. You can explicitly reply from your Telegram account with Send as me. TG Flow does not change Telegram read receipts. Mark as read only updates your TG Flow summary checkpoint.</p>
      </div>
    </details>
  )
}

export default function ChatsPage() {
  const { isAuthenticated } = useAuth()
  const { isTelegram, initData, backButton, haptic } = useTelegram()
  const queryClient = useQueryClient()
  const telegramInitData = isTelegram ? initData : undefined
  const [selectedChatId, setSelectedChatId] = useState<number | null>(null)
  const [modeError, setModeError] = useState<string | null>(null)
  const [replyTargets, setReplyTargets] = useState<Record<number, ChatMessage>>({})

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
  const replyTarget = selectedChatId === null ? undefined : replyTargets[selectedChatId]
  const messagesQuery = useQuery<ChatMessage[]>({
    queryKey: ['chatMessages', selectedChatId, selectedChat?.capture_mode_changed_at],
    queryFn: () => api.getChatMessages(selectedChatId || 0, telegramInitData),
    enabled: isAuthenticated && selectedChat?.capture_mode === 'full',
    refetchInterval: selectedChat?.capture_mode === 'full' && !isBusinessDisconnected(selectedChat) ? 15_000 : false,
  })

  // A snapshot stays fixed until an explicit refresh or acknowledgement. New
  // arrivals must not silently expand the boundary the user is acknowledging.
  const unreadQuery = useQuery<UnreadChatMessages>({
    queryKey: ['chatUnread', selectedChatId, selectedChat?.capture_mode_changed_at, selectedChat?.read_through_message_id],
    queryFn: ({ signal }) => api.getUnreadChatMessages(selectedChatId || 0, selectedChat?.capture_mode_changed_at || '', telegramInitData, signal),
    enabled: isAuthenticated && selectedChat?.capture_mode === 'full',
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  })
  const snapshot = unreadQuery.data
  const canMarkRead = selectedChat?.capture_mode === 'full' && selectedChat.unread_count > 0 &&
    snapshot?.capture_mode_changed_at === selectedChat.capture_mode_changed_at &&
    snapshot.messages.length > 0 && snapshot.snapshot_through_message_id > selectedChat.read_through_message_id

  const readMutation = useMutation({
    mutationFn: ({ chatId, throughMessageId, generation }: { chatId: number; throughMessageId: number; generation: string }) =>
      api.markChatRead(chatId, throughMessageId, generation, telegramInitData),
    onSuccess: async (updated, submitted) => {
      await queryClient.cancelQueries({ queryKey: ['chatUnread', submitted.chatId] })
      queryClient.removeQueries({ queryKey: ['chatUnread', submitted.chatId] })
      queryClient.setQueryData<ChatSubscription[]>(['chats'], (current) => current?.map((chat) =>
        chat.chat_id === submitted.chatId && chat.capture_mode_changed_at === submitted.generation ? updated : chat
      ))
      await queryClient.invalidateQueries({ queryKey: ['chats'] })
    },
  })

  const modeMutation = useMutation({
    mutationFn: ({ chatId, mode }: { chatId: number; mode: CaptureMode }) =>
      api.updateChatMode(chatId, mode, telegramInitData),
    onMutate: () => setModeError(null),
    onSuccess: async (updated) => {
      // Discard in-flight and cached full feeds before publishing the new mode.
      await queryClient.cancelQueries({ queryKey: ['chatMessages', updated.chat_id] })
      queryClient.removeQueries({ queryKey: ['chatMessages', updated.chat_id] })
      await queryClient.cancelQueries({ queryKey: ['chatUnread', updated.chat_id] })
      queryClient.removeQueries({ queryKey: ['chatUnread', updated.chat_id] })
      queryClient.setQueryData<ChatSubscription[]>(['chats'], (current) =>
        current?.map((chat) => (chat.chat_id === updated.chat_id ? updated : chat)) || [updated]
      )
    },
    onError: () => setModeError('Couldn’t change the capture mode. Try again.'),
  })

  const selectMode = (chat: ChatSubscription, mode: CaptureMode) => {
    if (chat.source === 'business' && (mode === 'mentions' || (mode === 'full' && !chat.connection_active))) return
    haptic?.impactOccurred('light')
    if (chat.capture_mode !== mode) modeMutation.mutate({ chatId: chat.chat_id, mode })
  }

  return (
    <div className="cosmos-page">
      <header className="topbar">
        <div className="topbar-inner">
          <Link to="/" className="back-link">← Home</Link>

          <button className="refresh-button" onClick={() => chatsQuery.refetch()} aria-label="Refresh chats">↻</button>
        </div>
      </header>
      <main className="page-wrap capture-page">
        <div className="inbox-heading">
          <div><h1>Chats</h1></div>
          <p>Review your groups and connected personal chats. Change how messages are saved or disable a subscription here.</p>
        </div>

        <BusinessSetup />

        {chatsQuery.isLoading && <p className="lede">Loading chat subscriptions…</p>}
        {chatsQuery.error && <div className="error-box">Couldn’t load your chats.</div>}
        {modeError && <div className="error-box" role="alert">{modeError}</div>}
        {!chatsQuery.isLoading && chatsQuery.data?.length === 0 && (
          <div className="panel capture-empty"><p>Add the bot to a group. The person who adds it is automatically subscribed to all new messages.</p><p>If your group was added before automatic subscriptions, remove and re-add the bot once. Allow the bot to read group messages through Telegram’s privacy settings or group admin permissions.</p></div>
        )}

        <div className="capture-grid">
          <section className="capture-list">
            {chatsQuery.data?.map((chat) => (
              <article key={chat.id} className={`panel capture-card${selectedChatId === chat.chat_id ? ' selected' : ''}`}>
                <button className="capture-card-heading" onClick={() => setSelectedChatId(chat.chat_id)}>
                  <span><strong>{chat.title || chat.username || `Chat ${chat.chat_id}`}</strong><small>{chat.source === 'business' ? `Private chat · Telegram Business · ${chat.connection_active ? 'Connected' : 'Disconnected'}` : chat.username ? `@${chat.username}` : chat.chat_type}</small></span>
                  <span className="chat-unread-count">{chat.unread_count} unread</span>
                  <span className={`mode-badge ${chat.capture_mode}`}>{chat.capture_mode === 'disabled' ? 'Disabled' : chat.capture_mode === 'full' ? 'Full chat' : 'Mentions'}</span>
                </button>
                <div className="mode-switch" role="group" aria-label={`Capture mode for ${chat.title || chat.username || chat.chat_id}`}>
                  {chat.source !== 'business' && <button aria-pressed={chat.capture_mode === 'mentions'} className={chat.capture_mode === 'mentions' ? 'active' : ''} onClick={() => selectMode(chat, 'mentions')} disabled={modeMutation.isPending || readMutation.isPending}>Mentions + context</button>}
                  <button aria-pressed={chat.capture_mode === 'full'} className={chat.capture_mode === 'full' ? 'active' : ''} onClick={() => selectMode(chat, 'full')} disabled={modeMutation.isPending || readMutation.isPending || isBusinessDisconnected(chat)}>All messages</button>
                </div>
                <p className="mode-copy">{captureDescription(chat)}</p>
                <div className="capture-actions">
                  <button className="secondary-button" disabled={modeMutation.isPending || readMutation.isPending || (chat.capture_mode === 'disabled' && isBusinessDisconnected(chat))} onClick={() => selectMode(chat, chat.capture_mode === 'disabled' ? 'full' : 'disabled')}>
                    {chat.capture_mode === 'disabled' ? 'Re-enable · All messages' : 'Disable subscription'}
                  </button>
                </div>
              </article>
            ))}
          </section>

          <section className="panel full-feed">
            {!selectedChat && <p className="feed-placeholder">Select a chat to inspect its capture mode.</p>}
            {selectedChat?.capture_mode === 'disabled' && <p className="feed-placeholder">{isBusinessDisconnected(selectedChat) ? 'Saving is disabled and Telegram Business is disconnected. Reconnect the bot in Telegram, then re-enable All messages. Messages sent while saving was unavailable are not backfilled.' : 'This subscription is disabled. Re-enable it to collect new messages; messages sent while disabled are not backfilled.'}</p>}
            {selectedChat?.capture_mode === 'mentions' && <p className="feed-placeholder">This chat is in mention mode. Switch to “All messages” to start a complete feed.</p>}
            {selectedChat?.capture_mode === 'full' && (
              <>
                <div className="feed-heading"><h2>{selectedChat.title || `Chat ${selectedChat.chat_id}`}</h2><span>{messagesQuery.data?.length || 0} messages</span></div>
                {isBusinessDisconnected(selectedChat) && <p className="feed-placeholder">Saved history is still available to you. Reconnect the bot in your Telegram account settings to collect new messages.</p>}
                <section className="unread-controls" aria-label="Unread messages">
                  <div className="unread-actions">
                    <strong>{selectedChat.unread_count} unread</strong>
                    <button className="secondary-button" disabled={unreadQuery.isFetching || readMutation.isPending || modeMutation.isPending} onClick={() => { void unreadQuery.refetch(); void chatsQuery.refetch() }}>Refresh unread</button>
                    <button className="primary-button" disabled={!canMarkRead || unreadQuery.isFetching || readMutation.isPending || modeMutation.isPending} onClick={() => {
                      if (canMarkRead && snapshot) readMutation.mutate({ chatId: selectedChat.chat_id, throughMessageId: snapshot.snapshot_through_message_id, generation: snapshot.capture_mode_changed_at })
                    }}>{readMutation.isPending && readMutation.variables?.chatId === selectedChat.chat_id ? 'Marking…' : 'Mark as read'}</button>
                  </div>
                  <p className="unread-copy">Read in TG Flow means acknowledged here or after a GPT summary, independently of Telegram. Opening this chat does not mark messages as read.</p>
                  {unreadQuery.isLoading && <p role="status">Loading unread snapshot…</p>}
                  {unreadQuery.isError && <p role="alert">Couldn’t load unread messages. Refresh unread to try again.</p>}
                  {readMutation.isError && readMutation.variables?.chatId === selectedChat.chat_id && <p role="alert">Couldn’t confirm the update. Refresh unread to check your read position.</p>}
                  {snapshot && snapshot.messages.length > 0 && <>
                    <p className="unread-copy">Mark as read acknowledges the snapshot through message #{snapshot.snapshot_through_message_id}. Messages arriving after this snapshot stay unread.</p>
                    {snapshot.has_more && <p className="unread-copy"><strong>This snapshot contains more than the {snapshot.messages.length} oldest messages shown below. Mark as read includes all messages through #{snapshot.snapshot_through_message_id}, including those not shown.</strong></p>}
                    <details className="unread-preview"><summary>Preview unread messages ({snapshot.messages.length}{snapshot.has_more ? '+' : ''})</summary><div className="feed-messages">{snapshot.messages.map((message) => <Message key={message.id} message={message} />)}</div></details>
                  </>}
                </section>
                {messagesQuery.isLoading && <p className="feed-placeholder">Loading messages…</p>}
                {messagesQuery.error && <div className="error-box">Couldn’t load the full feed.</div>}
                <div className="feed-messages">{messagesQuery.data?.map((message) => <Message key={message.id} message={message} onReply={selectedChat.source === 'business' && selectedChat.connection_active && !modeMutation.isPending ? () => setReplyTargets(current => ({ ...current, [selectedChat.chat_id]: message })) : undefined} />)}</div>
                {!messagesQuery.isLoading && messagesQuery.data?.length === 0 && <p className="feed-placeholder">{isBusinessDisconnected(selectedChat) ? 'No saved messages in this capture period.' : 'New messages will appear here.'}</p>}
              </>
            )}
            <BusinessReplyComposer chat={selectedChat} target={replyTarget} targetVisible={Boolean(messagesQuery.data?.some(message => message.message_id === replyTarget?.message_id))} initData={telegramInitData} onSent={async (chatId) => {
              await Promise.all([
                queryClient.invalidateQueries({ queryKey: ['chatMessages', chatId] }),
                queryClient.invalidateQueries({ queryKey: ['chats'] }),
              ])
            }} />
          </section>
        </div>
      </main>
    </div>
  )
}
