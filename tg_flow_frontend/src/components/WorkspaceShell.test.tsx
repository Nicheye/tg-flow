// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { WorkspaceShell } from './WorkspaceShell'

const mocks = vi.hoisted(() => ({ logout: vi.fn() }))
vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({ isAuthenticated: true, user: { full_name: 'Alex', tg_username: 'alex' }, logout: mocks.logout }),
}))
vi.mock('../hooks/useTelegram', () => ({ useTelegram: () => ({ isTelegram: false }) }))

afterEach(() => { cleanup(); vi.clearAllMocks() })

it('keeps navigation and sign-out available in the workspace', () => {
  render(<MemoryRouter initialEntries={['/chats']}><WorkspaceShell><main>Chat content</main></WorkspaceShell></MemoryRouter>)
  expect(screen.getByRole('link', { name: 'Chats' })).toHaveAttribute('aria-current', 'page')
  expect(screen.getByRole('link', { name: 'Mentions' })).toHaveAttribute('href', '/mentions')
  fireEvent.click(screen.getByRole('button', { name: 'Sign out' }))
  expect(mocks.logout).toHaveBeenCalledOnce()
  expect(screen.getByText('Chat content')).toBeInTheDocument()
})
