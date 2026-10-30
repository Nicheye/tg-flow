import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'

interface ProtectedRouteProps {
  children: React.ReactNode
}

export function ProtectedRoute({ children }: ProtectedRouteProps) {
  const { isAuthenticated, isLoading } = useAuth()
  const location = useLocation()

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-dvh bg-zinc-50">
        <div className="flex flex-col items-center gap-4">
          <div className="relative">
            <div className="w-8 h-8 rounded-full border border-zinc-800" />
            <div className="absolute inset-0 w-8 h-8 rounded-full border border-transparent border-t-violet-500 animate-spin" />
          </div>
          <p className="text-zinc-500 text-sm">Checking auth...</p>
        </div>
      </div>
    )
  }

  if (!isAuthenticated) {
    // Redirect to login, preserving the intended destination
    return <Navigate to="/login" state={{ from: location }} replace />
  }

  return <>{children}</>
}

export function PublicRoute({ children }: ProtectedRouteProps) {
  const { isAuthenticated, isLoading } = useAuth()
  const location = useLocation()

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-dvh bg-zinc-50">
        <div className="relative">
          <div className="w-8 h-8 rounded-full border border-zinc-800" />
          <div className="absolute inset-0 w-8 h-8 rounded-full border border-transparent border-t-violet-500 animate-spin" />
        </div>
      </div>
    )
  }

  if (isAuthenticated) {
    // Redirect to home or the intended destination
    const from = location.state?.from?.pathname || '/'
    return <Navigate to={from} replace />
  }

  return <>{children}</>
}

