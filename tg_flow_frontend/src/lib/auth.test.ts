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
})
