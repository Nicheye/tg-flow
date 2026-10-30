import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { createServer, request } from 'node:http'

const docker = (...args) => execFileSync('docker', args, { encoding: 'utf8' }).trim()
const upstream = createServer((request, response) => {
  const chunks = []
  request.on('data', chunk => chunks.push(chunk))
  request.on('end', () => {
    if (request.url === '/mcp?host-check=1') {
      response.writeHead(request.headers.host === 'localhost:3000' ? 200 : 421)
      response.end(request.headers.host)
      return
    }
    if (request.url === '/mcp?stream=1') {
      response.writeHead(200, { 'Content-Type': 'text/event-stream', 'Mcp-Session-Id': 'session-123' })
      response.write('data: first\n\n')
      setTimeout(() => response.end('data: second\n\n'), 1500)
      return
    }
    response.writeHead(200, { 'Content-Type': 'application/json' })
    response.end(JSON.stringify({
      method: request.method,
      url: request.url,
      body: Buffer.concat(chunks).toString(),
      cookie: request.headers.cookie,
      proto: request.headers['x-forwarded-proto'],
      authorization: request.headers.authorization,
      accept: request.headers.accept,
      session: request.headers['mcp-session-id'],
      protocol: request.headers['mcp-protocol-version'],
      host: request.headers.host,
    }))
  })
})

const containers = []
try {
  await new Promise(resolve => upstream.listen(0, '0.0.0.0', resolve))
  const image = docker('build', '-q', '.')
  const start = (rules = '') => {
    const id = docker('run', '-d', '--rm', '-p', '127.0.0.1::80',
      '--add-host', 'host.docker.internal:host-gateway',
      '-e', `BOT_API_UPSTREAM=http://host.docker.internal:${upstream.address().port}`,
      '-e', `TRUSTED_PROXY_RULES=${rules}`, image)
    containers.push(id)
    return `http://127.0.0.1:${docker('port', id, '80/tcp').split(':').pop()}`
  }
  const origin = start()

  const waitReady = async base => {
    let ready = false
    for (let attempt = 0; attempt < 50 && !ready; attempt++) {
      try {
        ready = (await fetch(`${base}/`)).ok
      } catch {
        await new Promise(resolve => setTimeout(resolve, 100))
      }
    }
    assert.ok(ready, 'nginx did not start')
  }
  await waitReady(origin)

  for (const path of [
    '/api/auth/me/?check=1',
    '/.well-known/oauth-authorization-server',
    '/.well-known/oauth-protected-resource/mcp',
    '/.well-known/example.json',
    '/oauth/authorize?client_id=example',
    '/oauth',
  ]) {
    const response = await fetch(`${origin}${path}`)
    assert.equal(response.status, 200, path)
    assert.equal((await response.json()).url, path)
  }

  const response = await fetch(`${origin}/oauth/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded', Cookie: 'session=test' },
    body: 'grant_type=authorization_code',
  })
  assert.deepEqual(await response.json(), {
    method: 'POST', url: '/oauth/token', body: 'grant_type=authorization_code', cookie: 'session=test', proto: 'http', accept: '*/*', host: new URL(origin).host,
  })

  const mcp = await fetch(`${origin}/mcp?query=1`, {
    method: 'POST',
    headers: { Authorization: 'Bearer example', Accept: 'application/json, text/event-stream',
      'Content-Type': 'application/json', 'Mcp-Session-Id': 'session-123', 'Mcp-Protocol-Version': '2025-03-26' },
    body: '{"jsonrpc":"2.0"}',
  })
  assert.deepEqual(await mcp.json(), {
    method: 'POST', url: '/mcp?query=1', body: '{"jsonrpc":"2.0"}', proto: 'http',
    authorization: 'Bearer example', accept: 'application/json, text/event-stream',
    session: 'session-123', protocol: '2025-03-26', host: new URL(origin).host,
  })

  const requestWithHost = (path, host) => new Promise((resolve, reject) => {
    const req = request(`${origin}${path}`, { headers: { Host: host } }, res => {
      const chunks = []
      res.on('data', chunk => chunks.push(chunk))
      res.on('end', () => resolve({ status: res.statusCode, body: Buffer.concat(chunks).toString() }))
    })
    req.on('error', reject)
    req.end()
  })
  for (const path of ['/api/auth/me/', '/oauth', '/.well-known/oauth-authorization-server', '/mcp']) {
    const result = await requestWithHost(path, 'localhost:3000')
    assert.equal(JSON.parse(result.body).host, 'localhost:3000', path)
  }
  const allowedHost = await requestWithHost('/mcp?host-check=1', 'localhost:3000')
  assert.equal(allowedHost.status, 200)
  const rejectedHost = await requestWithHost('/mcp?host-check=1', 'attacker.example:3000')
  assert.equal(rejectedHost.status, 421)
  const malformedHost = await requestWithHost('/mcp?host-check=1', 'bad..host:3000')
  assert.equal(malformedHost.status, 400)

  const stream = await fetch(`${origin}/mcp?stream=1`, { headers: { Accept: 'text/event-stream' } })
  assert.match(stream.headers.get('content-type'), /text\/event-stream/)
  assert.equal(stream.headers.get('mcp-session-id'), 'session-123')
  const reader = stream.body.getReader()
  const first = await Promise.race([
    reader.read(),
    new Promise((_, reject) => setTimeout(() => reject(new Error('MCP stream was buffered')), 800)),
  ])
  assert.match(new TextDecoder().decode(first.value), /data: first/)
  assert.match(new TextDecoder().decode((await reader.read()).value), /data: second/)

  const getProto = async (base, value) => {
    const result = await fetch(`${base}/api/auth/me/`, {
      headers: value === undefined ? {} : { 'X-Forwarded-Proto': value },
    })
    return (await result.json()).proto
  }
  assert.equal(await getProto(origin, 'https'), 'http', 'untrusted peer must not spoof HTTPS')
  // Trust all peers only in this isolated test container; deployments must use specific proxy addresses.
  const trustedOrigin = start('0.0.0.0/0 1; ::/0 1;')
  await waitReady(trustedOrigin)
  assert.equal(await getProto(trustedOrigin, 'https'), 'https')
  assert.equal(await getProto(trustedOrigin, 'http'), 'http')
  assert.equal(await getProto(trustedOrigin), 'http')
  assert.equal(await getProto(trustedOrigin, 'https, http'), 'http')
  assert.equal(await getProto(trustedOrigin, 'invalid'), 'http')
  const spaResponse = await fetch(`${origin}/mentions`)
  assert.match(spaResponse.headers.get('content-type'), /text\/html/)
  assert.match(await spaResponse.text(), /<div id="root"><\/div>/)
  console.log('Proxy routing, MCP streaming, trusted schemes and SPA fallback verified')
} finally {
  for (const containerId of containers) docker('stop', containerId)
  await new Promise(resolve => upstream.close(resolve))
}
