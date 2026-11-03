// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import HomePage from './HomePage'
import MentionsPage from './MentionsPage'

vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({ isAuthenticated: true, isLoading: false, user: { full_name: 'Alex', tg_user_id: 42 } }),
}))
vi.mock('../hooks/useTelegram', () => ({ useTelegram: () => ({ isTelegram: false }) }))
vi.mock('../lib/api', () => ({ api: { getMentions: vi.fn().mockResolvedValue([]) } }))

afterEach(cleanup)

it.each([
  ['Overview', HomePage],
  ['Mentions', MentionsPage],
])('%s explains automatic subscription and links to controls', async (_, Page) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter><Page /></MemoryRouter></QueryClientProvider>)
  expect(await screen.findByText(/Add the bot to a group to automatically save all new messages for your account/i)).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Chats' })).toHaveAttribute('href', '/chats')
  expect(screen.queryByText('/subscribe')).not.toBeInTheDocument()
})
