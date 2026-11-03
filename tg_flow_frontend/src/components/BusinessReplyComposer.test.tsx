// @vitest-environment jsdom

import '@testing-library/jest-dom/vitest'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, type BusinessReplyResult, type ChatMessage, type ChatSubscription } from '../lib/api'
import BusinessReplyComposer from './BusinessReplyComposer'

vi.mock('../lib/api', () => ({ api: { replyToChatMessage: vi.fn(), getChatReplyAttempt: vi.fn() } }))

const firstId = '123e4567-e89b-42d3-a456-426614174000'
const secondId = '123e4567-e89b-42d3-a456-426614174001'
const chat: ChatSubscription = {
  id: 1, chat_id: 21, title: 'Alice', username: 'alice', chat_type: 'private', source: 'business',
  connection_active: true, telegram_chat_id: 987654321, capture_mode: 'full',
  capture_mode_changed_at: '2026-11-03T12:00:00Z', subscribed_at: '2026-11-03T11:00:00Z',
  read_through_message_id: 0, last_read_at: null, unread_count: 1,
}
const target: ChatMessage = { id: 7, chat_id: 21, message_id: 50, from_user_id: 99, from_username: 'alice', text: 'Synthetic question', message_date: '2026-11-03T12:05:00Z' }
const result = (status: BusinessReplyResult['status'] = 'sent', overrides: Partial<BusinessReplyResult> = {}): BusinessReplyResult => ({
  status, request_id: firstId, message_id: status === 'sent' ? 51 : null, reply_attached: status === 'sent', error_code: null, error: null, ...overrides,
})

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(r => { resolve = r })
  return { promise, resolve }
}

function setup(overrides: Partial<Parameters<typeof BusinessReplyComposer>[0]> = {}) {
  const onSent = vi.fn().mockResolvedValue(undefined)
  const props = { chat, target, targetVisible: true, onSent, ...overrides }
  const view = render(<BusinessReplyComposer {...props} />)
  return { ...view, props, onSent }
}

function compose(text = '  Synthetic answer  ') {
  fireEvent.change(screen.getByRole('textbox', { name: 'Your reply' }), { target: { value: text } })
  fireEvent.click(screen.getByRole('button', { name: 'Send as me' }))
}

describe('BusinessReplyComposer', () => {
  beforeEach(() => {
    sessionStorage.clear()
    vi.spyOn(crypto, 'randomUUID').mockReturnValueOnce(firstId).mockReturnValue(secondId)
    vi.mocked(api.replyToChatMessage).mockResolvedValue(result())
  })
  afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.resetAllMocks() })

  it('does not offer a composer for groups or without a selected target', () => {
    const { rerender, props } = setup({ chat: { ...chat, source: 'group' } })
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
    rerender(<BusinessReplyComposer {...props} chat={chat} target={undefined} />)
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  })

  it('requires explicit Send as me and uses app chat and captured message IDs', async () => {
    const { onSent } = setup({ initData: 'synthetic-init-data' })
    expect(screen.getByRole('region', { name: 'Reply to Alice' })).toBeInTheDocument()
    expect(screen.getByText(/Sent from your Telegram account/)).toBeInTheDocument()
    const input = screen.getByRole('textbox', { name: 'Your reply' })
    fireEvent.change(input, { target: { value: '  Synthetic answer  ' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(api.replyToChatMessage).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Send as me' }))
    await screen.findByText('Reply sent.')
    expect(api.replyToChatMessage).toHaveBeenCalledExactlyOnceWith(21, 50, 'Synthetic answer', firstId, 'synthetic-init-data')
    expect(onSent).toHaveBeenCalledExactlyOnceWith(21)
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  })

  it('rejects blank and overlong drafts and counts Unicode code points', () => {
    setup()
    const send = screen.getByRole('button', { name: 'Send as me' })
    expect(send).toBeDisabled()
    const input = screen.getByRole('textbox')
    fireEvent.change(input, { target: { value: '   ' } })
    expect(send).toBeDisabled()
    fireEvent.change(input, { target: { value: 'a'.repeat(4097) } })
    expect(send).toBeDisabled()
    fireEvent.change(input, { target: { value: '😀'.repeat(4096) } })
    expect(send).toBeEnabled()
    expect(screen.getByText('4096 / 4096 characters')).toBeInTheDocument()
    expect(api.replyToChatMessage).not.toHaveBeenCalled()
  })

  it.each([
    { chat: { ...chat, connection_active: false } },
    { chat: { ...chat, capture_mode: 'disabled' as const } },
    { targetVisible: false },
  ])('blocks a new send when connection/capture/target is unavailable (%j)', (override) => {
    setup(override)
    expect(screen.getByRole('button', { name: 'Send as me' })).toBeDisabled()
    expect(api.replyToChatMessage).not.toHaveBeenCalled()
  })

  it('blocks a rapid duplicate submit while pending', async () => {
    const pending = deferred<BusinessReplyResult>()
    vi.mocked(api.replyToChatMessage).mockReturnValue(pending.promise)
    setup()
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Synthetic answer' } })
    const send = screen.getByRole('button', { name: 'Send as me' })
    act(() => { fireEvent.click(send); fireEvent.click(send) })
    expect(api.replyToChatMessage).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('button', { name: 'Sending…' })).toBeDisabled()
    expect(screen.getByRole('textbox')).toHaveAttribute('readonly')
    await act(async () => { pending.resolve(result()) })
  })

  it('reports successful standalone fallback without retrying', async () => {
    vi.mocked(api.replyToChatMessage).mockResolvedValue(result('sent', { reply_attached: false }))
    setup(); compose()
    await screen.findByText('Message sent. Telegram could not attach it to the original message.')
    expect(api.replyToChatMessage).toHaveBeenCalledTimes(1)
  })

  it('preserves definite-failure draft and requires a new explicit attempt', async () => {
    vi.mocked(api.replyToChatMessage).mockResolvedValueOnce(result('failed', { error: 'Reply permission is missing.' })).mockResolvedValueOnce(result('sent', { request_id: secondId }))
    setup(); compose()
    await screen.findByText('Reply permission is missing.')
    expect(screen.getByRole('textbox')).toHaveValue('  Synthetic answer  ')
    expect(screen.queryByRole('button', { name: 'Send as me' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Edit and try a new attempt' }))
    expect(screen.getByRole('textbox')).not.toHaveAttribute('readonly')
    expect(api.replyToChatMessage).toHaveBeenCalledTimes(1)
    fireEvent.click(screen.getByRole('button', { name: 'Send as me' }))
    await screen.findByText('Reply sent.')
    expect(vi.mocked(api.replyToChatMessage).mock.calls[1][3]).toBe(secondId)
  })

  it('checks unknown delivery through GET only with the same UUID', async () => {
    vi.mocked(api.replyToChatMessage).mockResolvedValue(result('unknown', { error_code: 'delivery_pending' }))
    vi.mocked(api.getChatReplyAttempt).mockResolvedValue(result())
    setup(); compose()
    await screen.findByText(/reply attempt is still pending/)
    expect(screen.getByRole('textbox')).toHaveAttribute('readonly')
    fireEvent.click(screen.getByRole('button', { name: 'Check delivery' }))
    await screen.findByText('Reply sent.')
    expect(api.getChatReplyAttempt).toHaveBeenCalledExactlyOnceWith(21, firstId, undefined)
    expect(api.replyToChatMessage).toHaveBeenCalledTimes(1)
  })

  it('keeps a failed status lookup uncertain and never repeats POST', async () => {
    vi.mocked(api.replyToChatMessage).mockRejectedValue(new Error('network unavailable'))
    vi.mocked(api.getChatReplyAttempt).mockRejectedValue({ status: 404 })
    setup(); compose()
    await screen.findByText(/Delivery is uncertain/)
    fireEvent.click(screen.getByRole('button', { name: 'Check delivery' }))
    await screen.findByText(/No confirmed delivery result is available/)
    expect(api.replyToChatMessage).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('textbox')).toHaveValue('  Synthetic answer  ')
    fireEvent.click(screen.getByRole('button', { name: 'I’ve checked Telegram — start a new reply' }))
    expect(screen.getByRole('textbox')).toHaveValue('')
    expect(screen.getByRole('button', { name: 'Send as me' })).toBeDisabled()
    expect(api.replyToChatMessage).toHaveBeenCalledTimes(1)
  })

  it('isolates drafts for identical message IDs in different chats and targets', () => {
    const { rerender, props } = setup()
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Alice draft' } })
    const bob = { ...chat, chat_id: 22, title: 'Bob' }
    rerender(<BusinessReplyComposer {...props} chat={bob} target={{ ...target, chat_id: 22 }} />)
    expect(screen.getByRole('textbox')).toHaveValue('')
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Bob draft' } })
    rerender(<BusinessReplyComposer {...props} />)
    expect(screen.getByRole('textbox')).toHaveValue('Alice draft')
    rerender(<BusinessReplyComposer {...props} target={{ ...target, message_id: 49 }} />)
    expect(screen.getByRole('textbox')).toHaveValue('')
  })

  it('keeps pending results on the submitted chat when navigating away', async () => {
    const pending = deferred<BusinessReplyResult>()
    vi.mocked(api.replyToChatMessage).mockReturnValue(pending.promise)
    const { rerender, props, onSent } = setup()
    compose()
    const bob = { ...chat, chat_id: 22, title: 'Bob' }
    rerender(<BusinessReplyComposer {...props} chat={bob} target={{ ...target, chat_id: 22 }} />)
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Bob draft' } })
    await act(async () => { pending.resolve(result()) })
    expect(screen.getByRole('textbox')).toHaveValue('Bob draft')
    expect(screen.queryByText('Reply sent.')).not.toBeInTheDocument()
    expect(onSent).toHaveBeenCalledExactlyOnceWith(21)
    rerender(<BusinessReplyComposer {...props} />)
    expect(screen.getByText('Reply sent.')).toBeInTheDocument()
  })

  it('retains an uncertain attempt when navigating through groups or disabled mode', async () => {
    vi.mocked(api.replyToChatMessage).mockResolvedValue(result('unknown'))
    vi.mocked(api.getChatReplyAttempt).mockResolvedValue(result())
    const { rerender, props } = setup()
    compose(); await screen.findByText(/Delivery is uncertain/)
    rerender(<BusinessReplyComposer {...props} chat={undefined} target={undefined} />)
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
    rerender(<BusinessReplyComposer {...props} chat={{ ...chat, connection_active: false, capture_mode: 'disabled' }} />)
    expect(screen.getByRole('textbox')).toHaveValue('  Synthetic answer  ')
    expect(screen.getByRole('button', { name: 'I’ve checked Telegram — start a new reply' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Check delivery' }))
    await screen.findByText('Reply sent.')
    expect(api.replyToChatMessage).toHaveBeenCalledTimes(1)
  })

  it('treats explicit HTTP rejection as a failed request without status polling', async () => {
    vi.mocked(api.replyToChatMessage).mockRejectedValue({ status: 403 })
    setup(); compose()
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('The reply was rejected.'))
    expect(screen.queryByRole('button', { name: 'Check delivery' })).not.toBeInTheDocument()
    expect(api.getChatReplyAttempt).not.toHaveBeenCalled()
  })

  it('restores a locked attempt after reload without storing message text or sending again', async () => {
    vi.mocked(api.replyToChatMessage).mockRejectedValue(new Error('network unavailable'))
    vi.mocked(api.getChatReplyAttempt).mockResolvedValue(result())
    const { unmount } = setup()
    compose('Private synthetic draft')
    await screen.findByText(/Delivery is uncertain/)
    const saved = sessionStorage.getItem('tg-flow:business-reply-attempts:v1')!
    expect(saved).toContain(firstId)
    expect(saved).not.toContain('Private synthetic draft')
    expect(saved).not.toContain('Synthetic question')
    unmount()
    setup()
    expect(screen.getByRole('textbox')).toHaveAttribute('readonly')
    expect(screen.getByRole('textbox')).toHaveValue('')
    expect(screen.queryByRole('button', { name: 'Send as me' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Check delivery' }))
    await screen.findByText('Reply sent.')
    expect(api.replyToChatMessage).toHaveBeenCalledTimes(1)
    expect(api.getChatReplyAttempt).toHaveBeenCalledWith(21, firstId, undefined)
  })

  it.each(['SecurityError', 'QuotaExceededError'])('fails closed before POST when storage write fails (%s)', async name => {
    const storage = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new DOMException('Storage unavailable', name) })
    setup()
    compose('Preserved draft')
    expect(screen.getByRole('alert')).toHaveTextContent('Your browser could not save delivery status.')
    expect(screen.getByRole('textbox')).toHaveValue('Preserved draft')
    expect(screen.getByRole('textbox')).not.toHaveAttribute('readonly')
    expect(api.replyToChatMessage).not.toHaveBeenCalled()
    storage.mockRestore()
    fireEvent.click(screen.getByRole('button', { name: 'Send as me' }))
    await screen.findByText('Reply sent.')
    expect(api.replyToChatMessage).toHaveBeenCalledExactlyOnceWith(21, 50, 'Preserved draft', secondId, undefined)
  })

  it('fails closed before POST if persisted attempt metadata cannot be read back', async () => {
    const storage = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new DOMException('Storage unavailable', 'SecurityError') })
    const { unmount } = setup()
    compose('Preserved draft')
    expect(screen.getByRole('alert')).toHaveTextContent('Enable tab storage and reload this page')
    expect(screen.getByRole('textbox')).toHaveValue('Preserved draft')
    expect(screen.getByRole('textbox')).not.toHaveAttribute('readonly')
    expect(api.replyToChatMessage).not.toHaveBeenCalled()
    storage.mockRestore()
    // A page that could not recover earlier attempts must reload before sending.
    fireEvent.click(screen.getByRole('button', { name: 'Send as me' }))
    expect(api.replyToChatMessage).not.toHaveBeenCalled()
    unmount()
    setup()
    compose('Preserved draft')
    await screen.findByText('Reply sent.')
    expect(api.replyToChatMessage).toHaveBeenCalledTimes(1)
  })
})
