import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const template = readFileSync(new URL('../../tg_flow_bot/users/templates/oauth/login.html', import.meta.url), 'utf8')
const inline = template.match(/<script>([\s\S]*?)<\/script>/)[1]
  .replace(/{%[\s\S]*?%}/g, '')
  .replace(/{{ telegram_bot_username\|escapejs }}/g, 'fixture_bot')
const source = {}
const frame = { contentWindow: source }
const scripts = []
const requests = []
const error = { style: { display: 'none' } }
let handler
let webHandler
let accessToken = 'fixture-web-access'
let loginTabs = 0
let reloaded = false
const webButton = { addEventListener: (_event, callback) => { webHandler = callback } }
const widget = {
  querySelector: () => frame,
  appendChild: script => scripts.push(script),
}
const context = {
  window: {
    addEventListener: (event, callback) => {
      assert.equal(event, 'message')
      handler = callback
    },
    location: { reload: () => { reloaded = true } },
    open: url => { assert.equal(url, '/login'); loginTabs++ },
  },
  document: {
    getElementById: id => id === 'telegram-widget' ? widget : id === 'web-session-login' ? webButton : error,
    querySelector: () => ({ value: 'fixture-csrf' }),
    createElement: () => ({ dataset: {} }),
  },
  localStorage: { getItem: key => { assert.equal(key, 'access_token'); return accessToken } },
  fetch: async (url, options) => {
    requests.push({ url, options })
    return { ok: true }
  },
}
vm.runInNewContext(inline, context)
assert.equal(typeof handler, 'function', 'Widget message callback must be installed')
assert.equal(scripts.length, 1)
assert.equal(scripts[0].dataset.onauth, undefined, 'Widget must not evaluate a callback string')
assert.ok(!template.includes("'unsafe-eval'"), 'Keep eval blocked by CSP')
const user = { id: 123, first_name: 'Fixture', photo_url: 'https://t.me/i/userpic/fixture.jpg', auth_date: 1234, hash: 'fixture-signature' }
const data = JSON.stringify({ event: 'auth_user', auth_data: user })
handler({ origin: 'https://untrusted.example', source, data })
handler({ origin: 'https://oauth.telegram.org', source: {}, data })
handler({ origin: 'https://oauth.telegram.org', source, data: 'invalid json' })
handler({ origin: 'https://oauth.telegram.org', source, data: 'null' })
assert.equal(requests.length, 0, 'Untrusted or unsolicited messages cannot initiate authentication')
handler({ origin: 'https://oauth.telegram.org', source, data: JSON.stringify({ event: 'auth_user', init: true, auth_data: user }) })
await new Promise(resolve => setImmediate(resolve))
assert.equal(requests.length, 1, 'A remembered Telegram session must complete authentication')
assert.equal(reloaded, true)
requests.length = 0
reloaded = false
handler({ origin: 'https://oauth.telegram.org', source, data })
await new Promise(resolve => setImmediate(resolve))
assert.equal(requests.length, 1)
assert.equal(requests[0].url, '/oauth/session/telegram')
assert.equal(requests[0].options.headers['X-CSRFToken'], 'fixture-csrf')
const payload = JSON.parse(requests[0].options.body)
assert.equal(payload.photo_url, user.photo_url)
assert.equal(payload.hash, user.hash)
assert.equal(reloaded, true)
requests.length = 0
reloaded = false
await webHandler()
assert.equal(requests.length, 1)
assert.equal(requests[0].url, '/oauth/session/web')
assert.equal(requests[0].options.headers.Authorization, 'Bearer fixture-web-access')
assert.equal(requests[0].options.headers['X-CSRFToken'], 'fixture-csrf')
assert.equal(reloaded, true)
requests.length = 0
accessToken = null
await webHandler()
assert.equal(requests.length, 0)
assert.equal(loginTabs, 1)
scripts[0].onerror()
assert.equal(error.style.display, 'block', 'Script-load failures must be visible')
console.log('OAuth widget callback, origin/source checks, CSRF and signed fields: PASS')
