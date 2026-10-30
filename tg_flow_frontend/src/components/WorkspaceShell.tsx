import { NavLink, useLocation } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useTelegram } from '../hooks/useTelegram'

const navigation = [
  { to: '/', label: 'Overview', icon: 'overview' },
  { to: '/mentions', label: 'Mentions', icon: 'mentions' },
  { to: '/chats', label: 'Chats', icon: 'chats' },
] as const

function NavIcon({ name }: { name: typeof navigation[number]['icon'] }) {
  return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {name === 'overview' && <><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /></>}
    {name === 'mentions' && <><path d="M4 4h16v12H4z" /><path d="M4 16h5l1.5 2h3l1.5-2h5" /></>}
    {name === 'chats' && <path d="M4 5h16v11H9l-5 3V5Z" />}
  </svg>
}

export function WorkspaceShell({ children }: { children: React.ReactNode }) {
  const { pathname } = useLocation()
  const { user, isAuthenticated, logout } = useAuth()
  const { isTelegram } = useTelegram()

  if (pathname === '/login') return <>{children}</>

  const name = user?.full_name || user?.tg_username || 'Telegram account'
  return <div className="workspace-shell">
    <aside className="workspace-sidebar">
      <div className="workspace-sidebar-content">
        <p className="workspace-nav-label">WORKSPACE</p>
        <nav className="workspace-nav" aria-label="Main navigation">
          {navigation.map(({ to, label, icon }) => <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => `workspace-nav-link${isActive ? ' active' : ''}`}><NavIcon name={icon} /><span>{label}</span></NavLink>)}
        </nav>
      </div>
      <div className="workspace-account">
        <span className="workspace-account-avatar" aria-hidden="true">{isAuthenticated ? name.charAt(0).toUpperCase() : 'T'}</span>
        <span className="workspace-account-text"><strong>{isAuthenticated ? name : 'Your account'}</strong><small>{isAuthenticated ? (user?.tg_username ? `@${user.tg_username}` : 'Connected') : 'Not connected'}</small></span>
        {isAuthenticated && !isTelegram && <button type="button" className="workspace-signout" onClick={logout}>Sign out</button>}
      </div>
    </aside>
    <div className="workspace-main">{children}</div>
  </div>
}
