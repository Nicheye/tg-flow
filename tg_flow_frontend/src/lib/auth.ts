import { AUTH_API_URL } from './config'

export interface User {
  id: number
  tg_user_id: number
  tg_username: string | null
  email: string | null
  full_name: string | null
  created_at: string
  is_active: boolean
}

export interface TelegramAuthData {
  id: number
  first_name: string
  last_name?: string
  username?: string
  photo_url?: string
  auth_date: number
  hash: string
}

export interface AuthResponse {
  user: User
  access: string
  refresh: string
  created: boolean
}

class AuthService {
  private baseUrl: string

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl
  }

  async telegramAuth(data: TelegramAuthData, initData?: string): Promise<AuthResponse | null> {
    try {
      const response = await fetch(`${this.baseUrl}/telegram-auth/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...(initData ? { init_data: initData } : {}),
          tg_user_id: data.id,
          tg_username: data.username || null,
          first_name: data.first_name,
          last_name: data.last_name || null,
          auth_date: data.auth_date,
          hash: data.hash,
        }),
      })

      if (response.ok) {
        const result: AuthResponse = await response.json()
        this.setTokens(result.access, result.refresh)
        return result
      }

      console.error('Telegram auth failed:', response.status)
      return null
    } catch (err) {
      console.error('Telegram auth error:', err)
      return null
    }
  }

  async getCurrentUser(): Promise<User | null> {
    const token = this.getAccessToken()
    if (!token) return null

    try {
      const response = await fetch(`${this.baseUrl}/me/`, {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      })

      if (response.ok) {
        return response.json()
      }

      return null
    } catch (err) {
      console.error('Get current user error:', err)
      return null
    }
  }

  /**
   * Dev login - authenticate by tg_user_id only (doesn't modify user profile)
   * Use this for development/testing when user already exists
   */
  async loginByTgId(tgUserId: number): Promise<{ user: User; access: string; refresh: string } | null> {
    try {
      const response = await fetch(`${this.baseUrl}/login/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tg_user_id: tgUserId }),
      })

      if (response.ok) {
        const data = await response.json()
        this.setTokens(data.access, data.refresh)
        
        // Fetch full user data
        const user = await this.getCurrentUser()
        if (user) {
          return { user, access: data.access, refresh: data.refresh }
        }
      }

      console.error('Login by tg_user_id failed:', response.status)
      return null
    } catch (err) {
      console.error('Login error:', err)
      return null
    }
  }

  async refreshToken(): Promise<boolean> {
    const refreshToken = this.getRefreshToken()
    if (!refreshToken) return false

    try {
      const response = await fetch(`${this.baseUrl}/token/refresh/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh: refreshToken }),
      })

      if (response.ok) {
        const data = await response.json()
        localStorage.setItem('access_token', data.access)
        return true
      }

      // Refresh token expired - clear tokens
      this.clearTokens()
      return false
    } catch (err) {
      console.error('Token refresh error:', err)
      return false
    }
  }

  setTokens(access: string, refresh: string): void {
    localStorage.setItem('access_token', access)
    localStorage.setItem('refresh_token', refresh)
  }

  getAccessToken(): string | null {
    return localStorage.getItem('access_token')
  }

  getRefreshToken(): string | null {
    return localStorage.getItem('refresh_token')
  }

  clearTokens(): void {
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
  }

  isAuthenticated(): boolean {
    return !!this.getAccessToken()
  }
}

export const authService = new AuthService(AUTH_API_URL)
