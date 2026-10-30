import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  type ReactNode,
} from 'react'
import { useTelegram } from '../hooks/useTelegram'
import { authService, type User, type TelegramAuthData } from '../lib/auth'

interface AuthState {
  user: User | null
  isLoading: boolean
  isAuthenticated: boolean
  error: string | null
}

interface AuthContextType extends AuthState {
  loginWithTelegram: (data: TelegramAuthData) => Promise<boolean>
  loginWithInitData: (initData: string) => Promise<boolean>
  loginByTgId: (tgUserId: number) => Promise<boolean>
  logout: () => void
  refreshUser: () => Promise<void>
  clearError: () => void
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

const TOKEN_REFRESH_INTERVAL = 4 * 60 * 1000 // 4 minutes

async function authenticateWithInitData(initData: string) {
  const params = new URLSearchParams(initData)
  const userParam = params.get('user')
  const authDate = params.get('auth_date')
  const hash = params.get('hash')

  if (!userParam || !authDate || !hash) return null

  const userData = JSON.parse(userParam)
  return authService.telegramAuth({
    id: userData.id,
    first_name: userData.first_name,
    last_name: userData.last_name,
    username: userData.username,
    auth_date: parseInt(authDate),
    hash,
  }, initData)
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const { isTelegram, initData, user: tgUser } = useTelegram()
  
  const [state, setState] = useState<AuthState>({
    user: null,
    isLoading: true,
    isAuthenticated: false,
    error: null,
  })

  // Initialize auth state
  useEffect(() => {
    const initAuth = async () => {
      setState(prev => ({ ...prev, isLoading: true, error: null }))

      try {
        // If in Telegram Mini App with initData
        if (isTelegram && initData && tgUser) {
          const result = await authenticateWithInitData(initData)
          if (result) {
            setState({
              user: result.user,
              isAuthenticated: true,
              isLoading: false,
              error: null,
            })
          } else {
            setState({
              user: null,
              isAuthenticated: false,
              isLoading: false,
              error: 'Telegram authentication could not be verified.',
            })
          }
          return
        }

        // Check for existing tokens in localStorage (web flow)
        const accessToken = localStorage.getItem('access_token')
        if (accessToken) {
          const user = await authService.getCurrentUser()
          if (user) {
            setState({
              user,
              isAuthenticated: true,
              isLoading: false,
              error: null,
            })
            return
          } else {
            // Try to refresh token
            const refreshed = await authService.refreshToken()
            if (refreshed) {
              const user = await authService.getCurrentUser()
              if (user) {
                setState({
                  user,
                  isAuthenticated: true,
                  isLoading: false,
                  error: null,
                })
                return
              }
            }
            // Clear invalid tokens
            authService.clearTokens()
          }
        }
      } catch (err) {
        console.error('Auth init error:', err)
      }

      setState({
        user: null,
        isAuthenticated: false,
        isLoading: false,
        error: null,
      })
    }

    initAuth()
  }, [isTelegram, initData, tgUser])

  // Auto-refresh token
  useEffect(() => {
    if (!state.isAuthenticated || isTelegram) return

    const interval = setInterval(async () => {
      const refreshed = await authService.refreshToken()
      if (!refreshed) {
        setState({
          user: null,
          isAuthenticated: false,
          isLoading: false,
          error: 'Session expired. Please login again.',
        })
      }
    }, TOKEN_REFRESH_INTERVAL)

    return () => clearInterval(interval)
  }, [state.isAuthenticated, isTelegram])

  const loginWithTelegram = useCallback(async (data: TelegramAuthData): Promise<boolean> => {
    setState(prev => ({ ...prev, isLoading: true, error: null }))

    try {
      const result = await authService.telegramAuth(data)
      
      if (result) {
        setState({
          user: result.user,
          isAuthenticated: true,
          isLoading: false,
          error: null,
        })
        return true
      }
      
      setState(prev => ({
        ...prev,
        isLoading: false,
        error: 'Authentication failed. Please try again.',
      }))
      return false
    } catch (err) {
      setState(prev => ({
        ...prev,
        isLoading: false,
        error: err instanceof Error ? err.message : 'Authentication failed',
      }))
      return false
    }
  }, [])

  const loginWithInitData = useCallback(async (initData: string): Promise<boolean> => {
    setState(prev => ({ ...prev, isLoading: true, error: null }))

    try {
      const result = await authenticateWithInitData(initData)

      if (result) {
        setState({
          user: result.user,
          isAuthenticated: true,
          isLoading: false,
          error: null,
        })
        return true
      }

      setState(prev => ({ ...prev, isLoading: false }))
      return false
    } catch (err) {
      console.error('Init data auth error:', err)
      setState(prev => ({ ...prev, isLoading: false }))
      return false
    }
  }, [])

  // Dev mode login - only authenticate by tg_user_id (doesn't modify profile)
  const loginByTgId = useCallback(async (tgUserId: number): Promise<boolean> => {
    setState(prev => ({ ...prev, isLoading: true, error: null }))

    try {
      const result = await authService.loginByTgId(tgUserId)
      
      if (result) {
        setState({
          user: result.user,
          isAuthenticated: true,
          isLoading: false,
          error: null,
        })
        return true
      }
      
      setState(prev => ({
        ...prev,
        isLoading: false,
        error: 'User not found. Please register via Telegram bot first.',
      }))
      return false
    } catch (err) {
      setState(prev => ({
        ...prev,
        isLoading: false,
        error: err instanceof Error ? err.message : 'Login failed',
      }))
      return false
    }
  }, [])

  const logout = useCallback(() => {
    authService.clearTokens()
    setState({
      user: null,
      isAuthenticated: false,
      isLoading: false,
      error: null,
    })
  }, [])

  const refreshUser = useCallback(async () => {
    if (!state.isAuthenticated) return

    const user = await authService.getCurrentUser()
    if (user) {
      setState(prev => ({ ...prev, user }))
    }
  }, [state.isAuthenticated])

  const clearError = useCallback(() => {
    setState(prev => ({ ...prev, error: null }))
  }, [])

  return (
    <AuthContext.Provider
      value={{
        ...state,
        loginWithTelegram,
        loginWithInitData,
        loginByTgId,
        logout,
        refreshUser,
        clearError,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}
