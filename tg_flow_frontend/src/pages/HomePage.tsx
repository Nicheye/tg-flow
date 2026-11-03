import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useTelegram } from '../hooks/useTelegram'
import { useAuth } from '../contexts/AuthContext'
import { api, type Mention } from '../lib/api'

function Arrow() {
  return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M5 12h13M13 6l6 6-6 6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>
}

export default function HomePage() {
  const { isTelegram, initData } = useTelegram()
  const { user, isAuthenticated, isLoading } = useAuth()
  const telegramInitData = isTelegram ? initData : undefined
  const { data: mentions, isLoading: mentionsLoading, isError: mentionsError, refetch } = useQuery<Mention[]>({
    queryKey: ['mentions'], queryFn: () => api.getMentions(telegramInitData), enabled: isAuthenticated,
  })
  const stats = useMemo(() => ({
    mentionsCount: mentions?.filter((mention) => !mention.is_archived).length || 0,
    chatsCount: new Set(mentions?.filter((mention) => !mention.is_archived).map((mention) => mention.chat_id) || []).size,
  }), [mentions])
  const name = user?.full_name || user?.tg_username || 'Your account'
  const showStats = isAuthenticated && !mentionsLoading && !mentionsError
  const recentMentions = (mentions || []).filter((mention) => !mention.is_archived).slice(0, 5)

  return <div className="cosmos-page">
    <header className="workspace-page-bar"><span>Workspace</span><span className="workspace-page-bar-divider">/</span><strong>Overview</strong></header>
    <main className="page-wrap">
      <div className="overview-heading"><div><p className="overview-kicker">YOUR WORKSPACE</p><h1 className="display-title">Overview</h1><p className="lede">Everything happening across your Telegram chats.</p></div>{isAuthenticated && <Link to="/mentions" className="secondary-button">Open inbox <Arrow /></Link>}</div>
      <section className="dashboard-grid" aria-label="Your workspace">
        <article className="panel identity-panel">
          {isLoading ? <div className="identity"><div className="avatar">·</div><div><p className="identity-name">Loading account</p><p className="identity-handle">Please wait</p></div></div> : user ? <div className="identity"><div className="avatar">{name.charAt(0).toUpperCase()}</div><div><h2 className="identity-name">{name}</h2><p className="identity-handle">{user.tg_username ? `@${user.tg_username}` : `Telegram ID: ${user.tg_user_id}`}</p></div></div> : <div><h2 className="identity-name">Connect your account</h2><p className="identity-handle">Sign in with Telegram to view your mentions.</p></div>}
          <div className="live-row">{isAuthenticated ? 'Signed in with Telegram' : 'Not signed in'}</div>
        </article>
        <div className="stat-stack">
          <article className="panel stat-panel"><div><div className="stat-label">Open mentions</div><div className="stat-value">{showStats ? stats.mentionsCount : '—'}</div></div></article>
          <article className="panel stat-panel"><div><div className="stat-label">Chats with mentions</div><div className="stat-value">{showStats ? stats.chatsCount : '—'}</div></div></article>
        </div>
      </section>
      {showStats && <p className="dashboard-note">Based on the latest 50 mentions.</p>}
      <section className="dashboard-inbox" aria-labelledby="recent-mentions-title">
        <div className="dashboard-section-heading"><div><h2 id="recent-mentions-title">Recent mentions</h2><p>Messages that need your attention.</p></div>{isAuthenticated && <Link className="dashboard-view-all" to="/mentions">View inbox <Arrow /></Link>}</div>
        <div className="dashboard-inbox-content">
          {isLoading || (isAuthenticated && mentionsLoading) ? <p className="dashboard-empty" role="status">Loading mentions…</p> :
            !isAuthenticated ? <div className="dashboard-empty"><p>Sign in to see your mentions here.</p>{!isTelegram && <Link to="/login" className="primary-button">Connect Telegram <Arrow /></Link>}</div> :
              mentionsError ? <div className="dashboard-empty" role="alert"><p>Couldn’t load your mentions.</p><button type="button" className="secondary-button" onClick={() => refetch()}>Try again</button></div> :
                recentMentions.length === 0 ? <div className="dashboard-empty"><p>No open mentions yet.</p><span>Add the bot to a group to automatically save all new messages for your account. Manage modes or disable your subscription in <Link to="/chats">Chats</Link>.</span></div> :
                  <ul className="dashboard-mentions">{recentMentions.map((mention) => <li key={mention.id}><Link to={`/mentions/${mention.id}`} state={{ mention }} className="dashboard-mention"><span className="dashboard-mention-avatar" aria-hidden="true">{(mention.chat_title || mention.chat_username || 'C').charAt(0).toUpperCase()}</span><span className="dashboard-mention-body"><span className="dashboard-mention-top"><strong>{mention.chat_title || mention.chat_username || `Chat ${mention.chat_id}`}</strong><time dateTime={mention.message_date}>{new Date(mention.message_date).toLocaleDateString()}</time></span><span className="dashboard-mention-author">{mention.from_username ? `@${mention.from_username}` : `User ${mention.from_user_id}`}</span><span className="dashboard-mention-text">{mention.text || '—'}</span></span><Arrow /></Link></li>)}</ul>}
        </div>
      </section>
    </main>
  </div>
}
