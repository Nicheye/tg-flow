import { useEffect, useRef, useState } from 'react'
import { api, type BusinessReplyResult, type ChatMessage, type ChatSubscription } from '../lib/api'

interface Draft {
  text: string
  requestId?: string
  submittedText?: string
  pending?: boolean
  checking?: boolean
  result?: BusinessReplyResult
  checkError?: string
}

interface Props {
  chat?: ChatSubscription
  target?: ChatMessage
  targetVisible: boolean
  initData?: string
  onSent: (chatId: number) => Promise<unknown>
}

const emptyDraft = (): Draft => ({ text: '' })
const storageKey = 'tg-flow:business-reply-attempts:v1'

function storedAttempts(): Record<string, Draft> {
  try {
    const value = JSON.parse(sessionStorage.getItem(storageKey) || '{}')
    const drafts: Record<string, Draft> = {}
    if (!value || typeof value !== 'object' || Array.isArray(value)) return drafts
    for (const [key, raw] of Object.entries(value)) {
      if (!/^\d+:\d+$/.test(key) || !raw || typeof raw !== 'object') continue
      const result = raw as BusinessReplyResult
      if (typeof result.request_id !== 'string' || !/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(result.request_id) || !['sent', 'failed', 'unknown'].includes(result.status)) continue
      drafts[key] = { text: '', requestId: result.request_id, result: { status: result.status, request_id: result.request_id, message_id: typeof result.message_id === 'number' ? result.message_id : null, reply_attached: result.reply_attached === true, error_code: result.status === 'unknown' ? 'delivery_unconfirmed' : null, error: null } }
    }
    return drafts
  } catch { return {} }
}

function persistAttempts(drafts: Record<string, Draft>): boolean {
  try {
    // Do not overwrite recoverable attempts when reads are currently blocked.
    sessionStorage.getItem(storageKey)
    const records = Object.fromEntries(Object.entries(drafts).filter(([, draft]) => draft.requestId).map(([key, draft]) => [key, {
      status: draft.result?.status || 'unknown', request_id: draft.requestId,
      message_id: draft.result?.message_id || null, reply_attached: draft.result?.reply_attached === true,
    }]))
    const encoded = JSON.stringify(records)
    sessionStorage.setItem(storageKey, encoded)
    // A successful write alone is insufficient: blocked reads would prevent
    // recovering the delivery identity after a reload.
    return sessionStorage.getItem(storageKey) === encoded
  } catch { return false }
}

// This component stays mounted when the selected chat changes. Each recipient
// and reply target keeps its own draft and delivery identity, including while a
// previous send is still in flight or its outcome is uncertain.
export default function BusinessReplyComposer({ chat, target, targetVisible, initData, onSent }: Props) {
  const initialReadFailed = useRef(false)
  const [drafts, setDrafts] = useState<Record<string, Draft>>(() => {
    try { sessionStorage.getItem(storageKey) } catch { initialReadFailed.current = true }
    return storedAttempts()
  })
  const busy = useRef(new Set<string>())
  const section = useRef<HTMLElement>(null)
  const selectionKey = chat?.source === 'business' && target ? `${chat.chat_id}:${target.message_id}` : undefined
  useEffect(() => { if (!initialReadFailed.current) persistAttempts(drafts) }, [drafts])
  useEffect(() => { if (selectionKey) section.current?.scrollIntoView?.({ block: 'nearest' }) }, [selectionKey])

  if (!chat || chat.source !== 'business' || !target) return null
  const chatId = chat.chat_id
  const key = `${chatId}:${target.message_id}`
  const draft = drafts[key] || emptyDraft()
  const recipient = chat.title || (chat.username ? `@${chat.username}` : `Chat ${chatId}`)
  const textLength = Array.from(draft.text.trim()).length
  const available = chat.connection_active && chat.capture_mode === 'full' && targetVisible
  const locked = Boolean(draft.requestId)

  function patch(update: Partial<Draft>) {
    setDrafts(current => ({ ...current, [key]: { ...(current[key] || emptyDraft()), ...update } }))
  }

  async function send() {
    if (!available || locked || busy.current.has(key) || textLength < 1 || textLength > 4096) return
    if (initialReadFailed.current) {
      patch({ checkError: 'Your browser could not read saved delivery status. Enable tab storage and reload this page to recover earlier attempts, or reply directly in Telegram. Nothing was sent.' })
      return
    }
    busy.current.add(key)
    const text = draft.text.trim()
    const requestId = crypto.randomUUID()
    // Keep delivery identity across a reload, without storing the message body.
    // Persist before dispatch so a lost HTTP response cannot unlock a new send.
    if (!persistAttempts({ ...drafts, [key]: { text: '', requestId } })) {
      busy.current.delete(key)
      patch({ checkError: 'Your browser could not save delivery status. Enable tab storage or reply directly in Telegram. Nothing was sent.' })
      return
    }
    patch({ requestId, submittedText: text, pending: true, checkError: undefined })
    let result: BusinessReplyResult
    try {
      result = await api.replyToChatMessage(chatId, target!.message_id, text, requestId, initData)
    } catch (error) {
      // A transport failure or 5xx may happen after Telegram accepted the send.
      // Lock this UUID and use only the read-only status endpoint to investigate.
      const status = typeof error === 'object' && error !== null && 'status' in error ? Number(error.status) : 0
      const definiteRejection = status >= 400 && status < 500
      result = {
        status: definiteRejection ? 'failed' : 'unknown', request_id: requestId,
        message_id: null, reply_attached: false,
        error_code: definiteRejection ? 'request_rejected' : 'delivery_unconfirmed',
        error: definiteRejection ? 'The reply was rejected. Refresh the chat and check its connection and reply permission.' : null,
      }
    }
    patch({ pending: false, result, ...(result.status === 'sent' ? { text: '' } : {}) })
    busy.current.delete(key)
    if (result.status === 'sent') await onSent(chatId).catch(() => undefined)
  }

  async function checkDelivery() {
    if (!draft.requestId || busy.current.has(key)) return
    busy.current.add(key)
    patch({ checking: true, checkError: undefined })
    try {
      // Never repeat POST here: if the first request never reached the server,
      // a repeated POST could create a send under a button labelled Check.
      const result = await api.getChatReplyAttempt(chatId, draft.requestId, initData)
      patch({ result, checking: false, ...(result.status === 'sent' ? { text: '' } : {}) })
      if (result.status === 'sent') await onSent(chatId).catch(() => undefined)
    } catch {
      patch({ checking: false, checkError: 'No confirmed delivery result is available. Check Telegram before starting another reply.' })
    } finally {
      busy.current.delete(key)
    }
  }

  const sent = draft.result?.status === 'sent'
  const unknown = draft.result?.status === 'unknown'
  return (
    <section ref={section} className="business-reply" aria-label={`Reply to ${recipient}`}>
      <div className="business-reply-heading"><strong>Reply to {recipient}</strong><span>Message #{target.message_id}</span></div>
      <blockquote className="business-reply-quote">{target.text || 'Message without text'}</blockquote>
      <p className="business-reply-copy">Sent from your Telegram account. Telegram requires reply permission and an incoming message in this chat within the last 24 hours.</p>
      {!available && <p role="status" className="business-reply-copy">{!chat.connection_active ? 'Reconnect Telegram Business to send a new reply.' : chat.capture_mode !== 'full' ? 'Enable All messages to send a new reply.' : 'The original message is no longer in this feed. Select an available message to reply.'}</p>}
      {sent ? <>
        <p role="status">{draft.result?.reply_attached ? 'Reply sent.' : 'Message sent. Telegram could not attach it to the original message.'}</p>
        <button type="button" className="secondary-button" disabled={!available} onClick={() => patch({ ...emptyDraft(), requestId: undefined, result: undefined, submittedText: undefined, checkError: undefined })}>Write another reply</button>
      </> : <>
        <label className="business-reply-label" htmlFor={`reply-${chatId}-${target.message_id}`}>Your reply</label>
        <textarea id={`reply-${chatId}-${target.message_id}`} value={draft.text} readOnly={locked} disabled={!available && !locked} rows={4} onChange={event => patch({ text: event.target.value })} aria-describedby={`reply-limit-${chatId}-${target.message_id}`} />
        <p id={`reply-limit-${chatId}-${target.message_id}`} className="business-reply-copy">{textLength} / 4096 characters</p>
        {draft.result?.status === 'failed' && <p role="alert">{draft.result.error || 'Telegram did not send the reply. Check reply permission and whether this chat had an incoming message in the last 24 hours.'}</p>}
        {unknown && <p role="alert">{draft.result?.error_code === 'delivery_pending' ? 'The reply attempt is still pending.' : 'Delivery is uncertain.'} Check Telegram before creating another reply. Checking delivery will not send a message.</p>}
        {draft.checkError && <p role="alert">{draft.checkError}</p>}
        <div className="business-reply-actions">
          {!locked && <button type="button" className="primary-button" disabled={!available || textLength < 1 || textLength > 4096} onClick={() => { void send() }}>Send as me</button>}
          {draft.pending && <button type="button" className="primary-button" disabled>Sending…</button>}
          {unknown && <>
            <button type="button" className="secondary-button" disabled={draft.checking} onClick={() => { void checkDelivery() }}>{draft.checking ? 'Checking…' : 'Check delivery'}</button>
            <button type="button" className="secondary-button" disabled={!available || draft.checking} onClick={() => patch({ ...emptyDraft(), requestId: undefined, result: undefined, submittedText: undefined, checkError: undefined })}>I’ve checked Telegram — start a new reply</button>
          </>}
          {draft.result?.status === 'failed' && <button type="button" className="secondary-button" disabled={!available} onClick={() => patch({ requestId: undefined, result: undefined, submittedText: undefined, checkError: undefined })}>Edit and try a new attempt</button>}
        </div>
      </>}
    </section>
  )
}
