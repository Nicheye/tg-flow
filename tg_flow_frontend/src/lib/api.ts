import { authService } from './auth'
import { API_URL } from './config'

interface ApiError {
  status: number
  message: string
}

class ApiClient {
  private baseUrl: string

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl
  }

  private async request<T>(
    endpoint: string,
    options: RequestInit = {},
    initData?: string
  ): Promise<T> {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...(options.headers as Record<string, string>),
    }

    // Use access token when available; include initData for Telegram Mini App
    const token = authService.getAccessToken()
    if (token) {
      headers['Authorization'] = `Bearer ${token}`
    }
    if (initData) {
      // For Telegram Mini App - send initData in special header
      headers['X-Telegram-Init-Data'] = initData
    }

    let response = await fetch(`${this.baseUrl}${endpoint}`, {
      ...options,
      headers,
    })

    // Handle 401 - try to refresh token
    if (response.status === 401 && !initData) {
      const refreshed = await authService.refreshToken()
      
      if (refreshed) {
        // Retry with new token
        const newToken = authService.getAccessToken()
        if (newToken) {
          headers['Authorization'] = `Bearer ${newToken}`
          response = await fetch(`${this.baseUrl}${endpoint}`, {
            ...options,
            headers,
          })
        }
      }
    }

    if (!response.ok) {
      const error: ApiError = {
        status: response.status,
        message: `API Error: ${response.status}`,
      }
      
      try {
        const data = await response.json()
        error.message = data.detail || data.message || error.message
      } catch {
        // Ignore JSON parse error
      }
      
      throw error
    }

    // Handle empty response
    const text = await response.text()
    if (!text) {
      return {} as T
    }

    return JSON.parse(text)
  }

  // Mentions
  async getMentions(initData?: string, chatId?: number, limit = 50, offset = 0) {
    const params = new URLSearchParams({
      limit: limit.toString(),
      offset: offset.toString(),
    })
    if (chatId) {
      params.append('chat_id', chatId.toString())
    }
    return this.request<Mention[]>(`/api/mentions/?${params}`, {}, initData)
  }

  // Get mention stats
  async getMentionStats(initData?: string) {
    return this.request<MentionStats>('/api/mentions/stats/', {}, initData)
  }

  // Reply to a mention
  async replyToMention(mentionId: number, text: string, initData?: string) {
    return this.request<ReplyResponse>(
      `/api/mentions/${mentionId}/reply`,
      {
        method: 'POST',
        body: JSON.stringify({ text }),
      },
      initData
    )
  }

  // Update a mention
  async updateMention(mentionId: number, isArchived: boolean, initData?: string) {
    return this.request<Mention>(
      `/api/mentions/${mentionId}`,
      {
        method: 'PATCH',
        body: JSON.stringify({ is_archived: isArchived }),
      },
      initData
    )
  }

  // Mention context (messages around mention)
  async getMentionContext(
    mentionId: number,
    before = 5,
    after = 5,
    initData?: string
  ) {
    const params = new URLSearchParams({
      before: before.toString(),
      after: after.toString(),
    })
    return this.request<MentionContextResponse>(
      `/api/mentions/${mentionId}/context?${params}`,
      {},
      initData
    )
  }

  async getChats(initData?: string) {
    return this.request<ChatSubscription[]>('/api/chats/', {}, initData)
  }

  async updateChatMode(chatId: number, captureMode: CaptureMode, initData?: string) {
    return this.request<ChatSubscription>(
      `/api/chats/${chatId}/mode`,
      {
        method: 'PATCH',
        body: JSON.stringify({ capture_mode: captureMode }),
      },
      initData
    )
  }

  async getChatMessages(chatId: number, initData?: string, limit = 100) {
    const params = new URLSearchParams({ limit: limit.toString() })
    return this.request<ChatMessage[]>(
      `/api/chats/${chatId}/messages?${params}`,
      {},
      initData
    )
  }
}

// Types
export interface Mention {
  id: number
  chat_id: number
  message_id: number
  from_user_id: number
  from_username: string | null
  text: string
  message_date: string
  link: string
  chat_title: string | null
  chat_username: string | null
  is_archived: boolean
}

export interface ChatMessage {
  id: number
  chat_id: number
  message_id: number
  from_user_id: number
  from_username: string | null
  text: string | null
  message_date: string
}

export type CaptureMode = 'mentions' | 'full'

export interface ChatSubscription {
  id: number
  chat_id: number
  title: string | null
  username: string | null
  chat_type: string
  capture_mode: CaptureMode
  capture_mode_changed_at: string
  subscribed_at: string
}

export interface MentionContextResponse {
  mention: Mention
  before: ChatMessage[]
  after: ChatMessage[]
}

export interface MentionStats {
  total_mentions: number
  total_chats: number
  recent_mentions: number
}

export interface ReplyResponse {
  success: boolean
  message_id?: number
  error?: string
}

export const api = new ApiClient(API_URL)
