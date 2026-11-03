import { useState, useMemo, useRef, useEffect } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useTelegram } from '../hooks/useTelegram'
import { useAuth } from '../contexts/AuthContext'
import { api, type Mention } from '../lib/api'
import { authService } from '../lib/auth'
import { API_URL } from '../lib/config'

interface ChatGroup {
  chatId: number
  chatName: string
  mentions: Mention[]
}

// Chat avatar component with photo loading and fallback
function ChatAvatar({ chatId, chatName }: { chatId: number; chatName: string }) {
  const [photoError, setPhotoError] = useState(false)
  const [photoUrl, setPhotoUrl] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    let objectUrl: string | null = null
    const token = authService.getAccessToken()

    if (!token) {
      setPhotoError(true)
      return () => controller.abort()
    }

    fetch(`${API_URL}/api/chats/${chatId}/photo`, {
      headers: { Authorization: `Bearer ${token}` },
      signal: controller.signal,
    })
      .then((response) => {
        if (!response.ok) throw new Error('Photo unavailable')
        return response.blob()
      })
      .then((blob) => {
        objectUrl = URL.createObjectURL(blob)
        setPhotoUrl(objectUrl)
      })
      .catch((error) => {
        if (error.name !== 'AbortError') setPhotoError(true)
      })

    return () => {
      controller.abort()
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [chatId])
  
  const getAvatarShade = (name: string): string => {
    const shades = ['#34383d', '#3f444a', '#494e54', '#51565d', '#5b626a']
    let hash = 0
    for (let i = 0; i < name.length; i++) {
      hash = name.charCodeAt(i) + ((hash << 5) - hash)
    }
    return shades[Math.abs(hash) % shades.length]
  }
  
  if (photoError || !photoUrl) {
    return (
      <div 
        className="chat-avatar-fallback w-9 h-9 rounded-lg flex items-center justify-center font-semibold text-sm"
        style={{ backgroundColor: getAvatarShade(chatName) }}
      >
        {chatName.charAt(0).toUpperCase()}
      </div>
    )
  }
  
  return (
    <img 
      src={photoUrl}
      alt={chatName}
      className="w-9 h-9 rounded-lg object-cover"
      onError={() => setPhotoError(true)}
    />
  )
}

// Reply input component
function ReplyInput({
  mention,
  onClose,
}: {
  mention: Mention
  onClose: () => void
}) {
  const { isTelegram, initData } = useTelegram()
  const [text, setText] = useState('')
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const queryClient = useQueryClient()
  const telegramInitData = isTelegram ? initData : undefined
  
  const replyMutation = useMutation({
    mutationFn: () => api.replyToMention(mention.id, text, telegramInitData),
    onSuccess: (data) => {
      if (data.success) {
        setText('')
        onClose()
        // Refresh mentions list and stats
        queryClient.invalidateQueries({ queryKey: ['mentions'] })
        queryClient.invalidateQueries({ queryKey: ['mentionStats'] })
      }
    },
  })

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (text.trim() && !replyMutation.isPending) {
      replyMutation.mutate()
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit(e)
    }
    if (e.key === 'Escape') {
      onClose()
    }
  }

  return (
    <div className="mt-3 bg-zinc-900/80 border border-white/[0.08] rounded-lg p-3">
      {/* Reply context */}
      <div className="flex items-center gap-2 mb-2 text-xs text-zinc-500">
        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M3 10h10a8 8 0 018 8v2M3 10l6 6m-6-6l6-6" />
        </svg>
        <span>Replying to {mention.from_username ? `@${mention.from_username}` : 'message'}</span>
      </div>
      
      {/* Input */}
      <form onSubmit={handleSubmit}>
        <textarea
          ref={inputRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Type your reply..."
          rows={2}
          className="w-full bg-black/50 border border-white/[0.08] rounded-lg px-3 py-2 text-sm text-white placeholder-zinc-600 resize-none focus:outline-none focus:border-violet-500/50 transition-colors"
          disabled={replyMutation.isPending}
        />
        
        {/* Error */}
        {replyMutation.isError && (
          <p className="text-red-400 text-xs mt-2">
            {(replyMutation.error as Error)?.message || 'Failed to send reply'}
          </p>
        )}
        
        {/* Actions */}
        <div className="flex items-center justify-between mt-2">
          <span className="text-zinc-600 text-xs">
            {text.length}/4096
          </span>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={onClose}
              className="px-3 py-1.5 text-zinc-400 hover:text-white text-xs transition-colors"
              disabled={replyMutation.isPending}
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!text.trim() || replyMutation.isPending}
              className="send-button px-3 py-1.5 disabled:bg-zinc-700 disabled:text-zinc-500 text-xs rounded-md transition-colors flex items-center gap-1.5"
            >
              {replyMutation.isPending ? (
                <>
                  <div className="w-3 h-3 border border-white/30 border-t-white rounded-full animate-spin" />
                  Sending...
                </>
              ) : (
                <>
                  <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
                  </svg>
                  Send
                </>
              )}
            </button>
          </div>
        </div>
      </form>
    </div>
  )
}

export default function MentionsPage() {
  const { isTelegram, initData, backButton, haptic } = useTelegram()
  const { user, isAuthenticated } = useAuth()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [expandedChats, setExpandedChats] = useState<Set<number>>(new Set())
  const [replyingTo, setReplyingTo] = useState<number | null>(null)
  const [archivingId, setArchivingId] = useState<number | null>(null)
  const [showArchived, setShowArchived] = useState(false)
  const [toastMessage, setToastMessage] = useState<string | null>(null)
  const toastTimerRef = useRef<number | null>(null)
  const telegramInitData = isTelegram ? initData : undefined

  if (isTelegram && backButton) {
    backButton.show()
    backButton.onClick(() => {
      window.history.back()
    })
  }

  useEffect(() => {
    return () => {
      if (toastTimerRef.current) {
        window.clearTimeout(toastTimerRef.current)
      }
    }
  }, [])

  const { data: allMentions, isLoading, error, refetch } = useQuery<Mention[]>({
    queryKey: ['mentions'],
    queryFn: () => api.getMentions(telegramInitData),
    enabled: isAuthenticated,
  })

  const archiveMutation = useMutation({
    mutationFn: (mentionId: number) =>
      api.updateMention(mentionId, true, telegramInitData),
    onMutate: async (mentionId) => {
      await queryClient.cancelQueries({ queryKey: ['mentions'] })
      const previousMentions = queryClient.getQueryData<Mention[]>(['mentions'])

      if (previousMentions) {
        const nextMentions = previousMentions.map((mention) =>
          mention.id === mentionId ? { ...mention, is_archived: true } : mention
        )
        queryClient.setQueryData(['mentions'], nextMentions)
      }

      setArchivingId(mentionId)
      return { previousMentions }
    },
    onError: (_error, _mentionId, context) => {
      if (context?.previousMentions) {
        queryClient.setQueryData(['mentions'], context.previousMentions)
      }
      setToastMessage('Failed to archive mention')
      if (toastTimerRef.current) {
        window.clearTimeout(toastTimerRef.current)
      }
      toastTimerRef.current = window.setTimeout(() => {
        setToastMessage(null)
        toastTimerRef.current = null
      }, 2200)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['mentions'] })
      queryClient.invalidateQueries({ queryKey: ['mentionStats'] })
    },
    onSettled: () => {
      setArchivingId(null)
    },
  })

  // Split mentions into active and archived
  const activeMentions = useMemo(() => 
    allMentions?.filter(m => !m.is_archived) || [], 
    [allMentions]
  )
  
  const archivedMentions = useMemo(() => 
    allMentions?.filter(m => m.is_archived) || [], 
    [allMentions]
  )

  const groupedMentions = useMemo((): ChatGroup[] => {
    if (!activeMentions.length) return []
    
    const groups = new Map<number, Mention[]>()
    activeMentions.forEach(mention => {
      const existing = groups.get(mention.chat_id) || []
      groups.set(mention.chat_id, [...existing, mention])
    })
    
    return Array.from(groups.entries()).map(([chatId, chatMentions]) => {
      const firstMention = chatMentions[0]
      const chatName = firstMention?.chat_title || getChatName(chatId)
      
      return {
        chatId,
        chatName,
        mentions: chatMentions.sort((a, b) => 
          new Date(b.message_date).getTime() - new Date(a.message_date).getTime()
        ),
      }
    })
  }, [activeMentions])

  useMemo(() => {
    if (groupedMentions.length > 0 && expandedChats.size === 0) {
      setExpandedChats(new Set(groupedMentions.map(g => g.chatId)))
    }
  }, [groupedMentions, expandedChats.size])

  useEffect(() => {
    if (activeMentions.length === 0 && archivedMentions.length > 0) {
      setShowArchived(true)
    }
  }, [activeMentions.length, archivedMentions.length])

  const toggleChat = (chatId: number) => {
    haptic?.impactOccurred('light')
    setExpandedChats(prev => {
      const next = new Set(prev)
      if (next.has(chatId)) {
        next.delete(chatId)
      } else {
        next.add(chatId)
      }
      return next
    })
  }

  const handleReplyClick = (e: React.MouseEvent, mentionId: number) => {
    e.stopPropagation()
    haptic?.impactOccurred('light')
    setReplyingTo(replyingTo === mentionId ? null : mentionId)
  }

  const handleMentionClick = (mention: Mention) => {
    if (replyingTo === mention.id) return // Don't open link if replying
    haptic?.impactOccurred('light')
    navigate(`/mentions/${mention.id}`, { state: { mention } })
  }

  const handleOpenTelegram = (e: React.MouseEvent, link: string) => {
    e.stopPropagation()
    haptic?.impactOccurred('light')
    window.open(link, '_blank')
  }

  const handleArchiveClick = (e: React.MouseEvent, mentionId: number) => {
    e.stopPropagation()
    haptic?.impactOccurred('light')
    setReplyingTo(null)
    if (!archiveMutation.isPending) {
      archiveMutation.mutate(mentionId)
    }
  }

  const formatDate = (dateString: string) => {
    const date = new Date(dateString)
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffMins = Math.floor(diffMs / 60000)
    const diffHours = Math.floor(diffMs / 3600000)
    const diffDays = Math.floor(diffMs / 86400000)

    if (diffMins < 1) return 'now'
    if (diffMins < 60) return `${diffMins}m`
    if (diffHours < 24) return `${diffHours}h`
    if (diffDays < 7) return `${diffDays}d`
    
    return date.toLocaleDateString('en', { day: 'numeric', month: 'short' })
  }

  function getChatName(chatId: number): string {
    if (chatId < 0) {
      return `Chat ${Math.abs(chatId).toString().slice(-6)}`
    }
    return `Chat ${chatId}`
  }

  return (
    <div className="cosmos-page mention-page">
      <header className="topbar">
        <div className="topbar-inner">
          {!isTelegram ? (
            <Link to="/" className="flex items-center gap-2 text-zinc-500 hover:text-white transition-colors">
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M10 19l-7-7m0 0l7-7m-7 7h18" />
              </svg>
              <span className="text-sm font-medium">Back</span>
            </Link>
          ) : (
            <div className="w-16" />
          )}



          <button
            onClick={() => refetch()}
            className="refresh-button"
            aria-label="Refresh mentions"
          >
            <svg className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
          </button>
        </div>
      </header>

      <main className="page-wrap">
        <div className="inbox-heading">
          <div>
            <h1>Mentions</h1>
          </div>
          <p>Decide what needs a response, then return to the thread with context.</p>
        </div>
        {user && (
          <div className="summary-line">
            <span>ACCOUNT</span>
            <strong>
              {user.tg_username ? `@${user.tg_username}` : user.full_name || `ID ${user.tg_user_id}`}
            </strong>
          </div>
        )}

        {isLoading && (
          <div className="flex flex-col items-center justify-center py-20">
            <div className="relative">
              <div className="w-8 h-8 rounded-full border border-zinc-800" />
              <div className="absolute inset-0 w-8 h-8 rounded-full border border-transparent border-t-violet-500 animate-spin" />
            </div>
            <p className="text-zinc-600 mt-4 text-sm">Loading...</p>
          </div>
        )}

        {error && (
          <div className="p-5 bg-zinc-900/50 border border-zinc-800 rounded-xl text-center">
            <p className="text-white font-medium text-sm">Failed to load</p>
            <p className="text-zinc-500 text-sm mt-1">Check your connection</p>
            <button
              onClick={() => refetch()}
              className="mt-4 px-4 py-2 bg-white/[0.06] hover:bg-white/[0.1] border border-white/[0.08] rounded-lg text-white text-sm transition-colors"
            >
              Retry
            </button>
          </div>
        )}

        {activeMentions.length === 0 && archivedMentions.length === 0 && !isLoading && !error && (
          <div className="text-center py-20">
            <div className="w-12 h-12 mx-auto mb-4 rounded-xl bg-zinc-900 border border-zinc-800 flex items-center justify-center">
              <svg className="w-6 h-6 text-zinc-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4" />
              </svg>
            </div>
            <h2 className="text-base font-semibold text-white mb-1">No mentions yet</h2>
            <p className="text-zinc-500 text-sm max-w-xs mx-auto">
              Add the bot to a group to automatically save all new messages for your account. Manage modes or disable your subscription in <Link to="/chats">Chats</Link>.
            </p>
          </div>
        )}

        {(groupedMentions.length > 0 || archivedMentions.length > 0) && (
          <div className="space-y-3">
            {groupedMentions.length > 0 && (
              <div className="summary-line">
                <span><strong>{activeMentions.length}</strong> MENTIONS</span>
                <span><strong>{groupedMentions.length}</strong> CHATS</span>
              </div>
            )}

            {groupedMentions.map((group) => (
              <div 
                key={group.chatId} 
                className="bg-zinc-900/40 border border-white/[0.06] rounded-xl overflow-hidden"
              >
                <button
                  onClick={() => toggleChat(group.chatId)}
                  className="w-full flex items-center justify-between p-3 hover:bg-white/[0.02] transition-colors"
                >
                  <div className="flex items-center gap-3">
                    <ChatAvatar chatId={group.chatId} chatName={group.chatName} />
                    <div className="text-left">
                      <h3 className="font-medium text-white text-sm">{group.chatName}</h3>
                      <p className="text-zinc-500 text-xs">{group.mentions.length} mentions</p>
                    </div>
                  </div>

                  <svg 
                    className={`w-4 h-4 text-zinc-500 transition-transform ${expandedChats.has(group.chatId) ? 'rotate-180' : ''}`} 
                    fill="none" 
                    viewBox="0 0 24 24" 
                    stroke="currentColor"
                    strokeWidth={2}
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                  </svg>
                </button>

                {expandedChats.has(group.chatId) && (
                  <div className="border-t border-white/[0.04]">
                    {group.mentions.map((mention, idx) => (
                      <div
                        key={mention.id}
                        className={`px-3 py-3 ${
                          idx !== group.mentions.length - 1 ? 'border-b border-white/[0.04]' : ''
                        }`}
                      >
                        <div 
                          onClick={() => handleMentionClick(mention)}
                          className="flex items-start gap-3 cursor-pointer group hover:bg-white/[0.02] -m-2 p-2 rounded-lg transition-colors"
                        >
                          <div className="mention-signal" />

                          <div className="flex-1 min-w-0">
                            <div className="flex items-center justify-between gap-2 mb-1">
                              <span className="text-zinc-500 text-xs">
                                {mention.from_username ? `@${mention.from_username}` : `User ${mention.from_user_id}`}
                              </span>
                              <span className="text-zinc-600 text-xs">
                                {formatDate(mention.message_date)}
                              </span>
                            </div>

                            <p className="text-zinc-200 text-sm leading-relaxed">
                              {mention.text}
                            </p>

                            {/* Actions */}
                            <div className="flex items-center gap-3 mt-2">
                              {/* Reply button */}
                              <button
                                onClick={(e) => handleReplyClick(e, mention.id)}
                                className={`flex items-center gap-1 text-xs transition-colors ${
                                  replyingTo === mention.id 
                                    ? 'text-violet-400' 
                                    : 'text-zinc-500 hover:text-violet-400'
                                }`}
                              >
                                <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                                  <path strokeLinecap="round" strokeLinejoin="round" d="M3 10h10a8 8 0 018 8v2M3 10l6 6m-6-6l6-6" />
                                </svg>
                                Reply
                              </button>

                              {/* Archive button */}
                              <button
                                onClick={(e) => handleArchiveClick(e, mention.id)}
                                className="flex items-center gap-1 text-xs text-zinc-500 hover:text-white transition-colors disabled:text-zinc-700"
                                disabled={archivingId === mention.id}
                              >
                                {archivingId === mention.id ? (
                                  <>
                                    <div className="w-3 h-3 border border-white/30 border-t-white rounded-full animate-spin" />
                                    Archiving
                                  </>
                                ) : (
                                  <>
                                    <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                                      <path strokeLinecap="round" strokeLinejoin="round" d="M20.25 7.5l-.625 10.632a2.25 2.25 0 01-2.247 2.118H6.622a2.25 2.25 0 01-2.247-2.118L3.75 7.5m8.25 3v6.75m0 0l-3-3m3 3l3-3M3.375 7.5h17.25c.621 0 1.125-.504 1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125z" />
                                    </svg>
                                    Archive
                                  </>
                                )}
                              </button>

                              {/* Open in Telegram */}
                              <button
                                onClick={(e) => handleOpenTelegram(e, mention.link)}
                                className="text-zinc-600 text-xs opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-1 hover:text-white"
                              >
                                <span>Open in Telegram</span>
                                <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                                  <path strokeLinecap="round" strokeLinejoin="round" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                                </svg>
                              </button>
                            </div>
                          </div>
                        </div>

                        {/* Reply input */}
                        {replyingTo === mention.id && (
                          <ReplyInput 
                            mention={mention} 
                            onClose={() => setReplyingTo(null)}
                          />
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}

            {/* Archived Section */}
            <div className="mt-6 pt-4 border-t border-white/[0.04]">
              <button
                onClick={() => {
                  haptic?.impactOccurred('light')
                  setShowArchived(!showArchived)
                }}
                className="w-full flex items-center justify-between py-2 text-zinc-500 hover:text-zinc-400 transition-colors"
              >
                <div className="flex items-center gap-2">
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M20.25 7.5l-.625 10.632a2.25 2.25 0 01-2.247 2.118H6.622a2.25 2.25 0 01-2.247-2.118L3.75 7.5m8.25 3v6.75m0 0l-3-3m3 3l3-3M3.375 7.5h17.25c.621 0 1.125-.504 1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125z" />
                  </svg>
                  <span className="text-sm">Archived</span>
                  {archivedMentions && archivedMentions.length > 0 && (
                    <span className="text-xs text-zinc-600">({archivedMentions.length})</span>
                  )}
                </div>
                <svg 
                  className={`w-4 h-4 transition-transform ${showArchived ? 'rotate-180' : ''}`} 
                  fill="none" 
                  viewBox="0 0 24 24" 
                  stroke="currentColor"
                  strokeWidth={2}
                >
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                </svg>
              </button>

              {showArchived && (
                <div className="mt-3 space-y-2">
                  {archivedMentions.length === 0 && (
                    <div className="text-center py-8">
                      <p className="text-zinc-600 text-sm">No archived mentions</p>
                    </div>
                  )}

                  {archivedMentions.length > 0 && (
                    <div className="space-y-2">
                      {archivedMentions.map((mention) => (
                        <div
                          key={mention.id}
                          onClick={() => handleMentionClick(mention)}
                          className="bg-zinc-900/30 border border-white/[0.04] rounded-lg p-3 cursor-pointer hover:bg-zinc-900/50 transition-colors group"
                        >
                          <div className="flex items-center justify-between gap-2 mb-1">
                            <div className="flex items-center gap-2">
                              <span className="text-zinc-600 text-xs">
                                {mention.chat_title || `Chat ${mention.chat_id}`}
                              </span>
                              <span className="text-zinc-700">•</span>
                              <span className="text-zinc-600 text-xs">
                                {mention.from_username ? `@${mention.from_username}` : `User ${mention.from_user_id}`}
                              </span>
                            </div>
                            <span className="text-zinc-700 text-xs">
                              {formatDate(mention.message_date)}
                            </span>
                          </div>
                          <p className="text-zinc-500 text-sm line-clamp-2">
                            {mention.text}
                          </p>
                          <button
                            onClick={(e) => handleOpenTelegram(e, mention.link)}
                            className="text-zinc-700 text-xs mt-2 opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-1 hover:text-white"
                          >
                            Open in Telegram
                            <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                              <path strokeLinecap="round" strokeLinejoin="round" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                            </svg>
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        )}
      </main>

      {toastMessage && (
        <div className="toast">
          <div className="flex items-center gap-2">
            <div className="w-1.5 h-1.5 rounded-full bg-red-400" />
            <span>{toastMessage}</span>
          </div>
        </div>
      )}

      {/* Footer */}
      <footer className="p-4 text-center border-t border-white/[0.06]">
        <p className="text-zinc-700 text-xs">
          Contact us: <a href="mailto:tagflow@atomicmail.io" className="text-zinc-500 hover:text-white transition-colors">tagflow@atomicmail.io</a>
        </p>
      </footer>
    </div>
  )
}
