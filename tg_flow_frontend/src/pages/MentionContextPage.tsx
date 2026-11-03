import { useMemo } from 'react'
import { Link, useLocation, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useTelegram } from '../hooks/useTelegram'
import { useAuth } from '../contexts/AuthContext'
import { api, type Mention, type MentionContextResponse, type ChatMessage } from '../lib/api'

type LocationState = { mention?: Mention }
function Message({ message, current = false }: { message: ChatMessage; current?: boolean }) {
  const date = new Date(message.message_date)
  return <article className={`message-card${current ? ' current' : ''}`}><div className="message-meta"><span>{message.from_username ? `@${message.from_username}` : `User ${message.from_user_id}`}</span><span>{date.toLocaleString('en', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</span></div><p className="message-text">{message.text || '—'}</p></article>
}
export default function MentionContextPage() {
  const { isTelegram, initData, backButton, haptic } = useTelegram(); const { isAuthenticated } = useAuth(); const { mentionId } = useParams(); const location = useLocation(); const state = location.state as LocationState | null; const mentionIdNum = mentionId ? Number(mentionId) : null; const mentionFromState = state?.mention
  if (isTelegram && backButton) { backButton.show(); backButton.onClick(() => window.history.back()) }
  const { data, isLoading, error } = useQuery<MentionContextResponse>({ queryKey: ['mentionContext', mentionIdNum], queryFn: () => api.getMentionContext(mentionIdNum || 0, 5, 5, isTelegram ? initData : undefined), enabled: isAuthenticated && !!mentionIdNum, placeholderData: mentionFromState ? { mention: mentionFromState, before: [], after: [] } : undefined, staleTime: 0 })
  const mention = data?.mention || mentionFromState
  const before = useMemo(() => [...(data?.before || [])].sort((a,b) => new Date(a.message_date).getTime() - new Date(b.message_date).getTime()), [data?.before]); const after = useMemo(() => [...(data?.after || [])].sort((a,b) => new Date(a.message_date).getTime() - new Date(b.message_date).getTime()), [data?.after])
  return <div className="cosmos-page"><header className="topbar"><div className="topbar-inner">{mention && <button onClick={() => { haptic?.impactOccurred('light'); window.open(mention.link, '_blank') }} className="secondary-button">Open Telegram</button>}</div></header><main className="context-layout"><Link to="/mentions" className="back-link">← Back to inbox</Link><div className="context-heading"><div><h1>Conversation context</h1><p>Read the messages around a mention before you answer.</p></div></div>{isLoading && <p className="lede">Retrieving the conversation…</p>}{error && <div className="error-box">Couldn’t load this context. Try again in a moment.</div>}{!isLoading && mention && <div className="message-rail"><p className="timeline-label">Earlier in the conversation</p>{before.length ? before.map((message) => <Message key={message.id} message={message} />) : <p className="lede">No earlier messages available.</p>}<p className="timeline-label current">Mention</p><Message current message={{ id: mention.id, chat_id: mention.chat_id, message_id: mention.message_id, from_user_id: mention.from_user_id, from_username: mention.from_username, text: mention.text, message_date: mention.message_date }} /><p className="timeline-label">What followed</p>{after.length ? after.map((message) => <Message key={message.id} message={message} />) : <p className="lede">No later messages available.</p>}</div>}</main></div>
}
