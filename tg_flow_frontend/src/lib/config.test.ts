import { afterEach, describe, expect, it, vi } from 'vitest'

describe('API URL configuration', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.resetModules()
  })

  it.each([
    { dev: true, override: '', expected: 'http://localhost:8081' },
    { dev: false, override: '', expected: '' },
    { dev: false, override: 'https://bot.example/', expected: 'https://bot.example' },
  ])('uses $expected for API requests', async ({ dev, override, expected }) => {
    vi.stubEnv('DEV', dev)
    vi.stubEnv('VITE_API_URL', override)
    const { API_URL } = await import('./config')
    expect(API_URL).toBe(expected)
  })
})
