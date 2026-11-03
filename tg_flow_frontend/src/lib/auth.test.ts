import { afterEach, describe, expect, it, vi } from 'vitest'

describe('auth API URL', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
    vi.resetModules()
  })

  it.each([
    { dev: true, bot: '', auth: '', expected: 'http://localhost:8081/api/auth/me/' },
    { dev: false, bot: '', auth: '', expected: '/api/auth/me/' },
    { dev: false, bot: 'https://bot.example/', auth: '', expected: 'https://bot.example/api/auth/me/' },
    { dev: false, bot: 'https://bot.example', auth: 'https://auth.example/custom/', expected: 'https://auth.example/custom/me/' },
  ])('requests $expected', async ({ dev, bot, auth, expected }) => {
    vi.stubEnv('DEV', dev)
    vi.stubEnv('VITE_API_URL', bot)
    vi.stubEnv('VITE_AUTH_API_URL', auth)
    vi.stubGlobal('localStorage', { getItem: () => 'access-token' })
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ id: 1 }) })
    vi.stubGlobal('fetch', fetchMock)

    const { authService } = await import('./auth')
    await authService.getCurrentUser()

    expect(fetchMock).toHaveBeenCalledWith(expected, {
      headers: { Authorization: 'Bearer access-token' },
    })
  })

  it('preserves the signed widget photo URL when sending Telegram authentication', async () => {
    vi.stubGlobal('localStorage', { setItem: vi.fn() })
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ user: { id: 1 }, access: 'access', refresh: 'refresh' }),
    })
    vi.stubGlobal('fetch', fetchMock)
    const widgetData = {
      id: 12345,
      username: 'example_user',
      first_name: 'Example',
      last_name: 'User',
      photo_url: 'https://t.me/i/userpic/320/example.jpg',
      auth_date: 1793440000,
      hash: 'signed-widget-hash',
    }

    const { authService } = await import('./auth')
    await authService.telegramAuth(widgetData)

    const body = JSON.parse(fetchMock.mock.calls[0][1].body)
    expect(body).toEqual({
      tg_user_id: widgetData.id,
      tg_username: widgetData.username,
      first_name: widgetData.first_name,
      last_name: widgetData.last_name,
      photo_url: widgetData.photo_url,
      auth_date: widgetData.auth_date,
      hash: widgetData.hash,
    })
  })
})
