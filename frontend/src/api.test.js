import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { clearPreferences, getPreferences, queryProductData, streamChat } from './api'

// Builds a fake fetch Response whose .body behaves enough like a real
// ReadableStream for streamChat()'s reader.read()/TextDecoder loop -
// encodes each event as a proper "data: {...}\n\n" SSE frame, the same
// shape the real backend emits (see backend/app/chat.py sse_event()).
function makeSSEResponse(events, { splitMidFrame = false } = {}) {
  const encoder = new TextEncoder()
  const raw = events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join('')
  const chunks = splitMidFrame
    ? [raw.slice(0, Math.floor(raw.length / 2)), raw.slice(Math.floor(raw.length / 2))]
    : [raw]
  const encoded = chunks.map((c) => encoder.encode(c))
  let i = 0
  return {
    ok: true,
    body: {
      getReader() {
        return {
          async read() {
            if (i < encoded.length) return { done: false, value: encoded[i++] }
            return { done: true, value: undefined }
          },
        }
      },
    },
  }
}

describe('streamChat', () => {
  beforeEach(() => {
    global.fetch = vi.fn()
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('dispatches step/token/final callbacks in order', async () => {
    const events = [
      { type: 'step', text: 'thinking' },
      { type: 'token', text: 'hello ' },
      { type: 'token', text: 'world' },
      { type: 'final', reply: 'hello world', matched_products: ['p1'], thinking_steps: ['thinking'] },
    ]
    global.fetch.mockResolvedValue(makeSSEResponse(events))

    const seen = []
    await streamChat('hi', 'en', 'ai', [], {
      onStep: (t) => seen.push(['step', t]),
      onToken: (t) => seen.push(['token', t]),
      onFinal: (evt) => seen.push(['final', evt]),
    })

    expect(seen[0]).toEqual(['step', 'thinking'])
    expect(seen[1]).toEqual(['token', 'hello '])
    expect(seen[2]).toEqual(['token', 'world'])
    expect(seen[3][0]).toBe('final')
    expect(seen[3][1].matched_products).toEqual(['p1'])
  })

  it('correctly reassembles an SSE frame split across two chunks', async () => {
    const events = [{ type: 'final', reply: 'ok', matched_products: [], thinking_steps: [] }]
    global.fetch.mockResolvedValue(makeSSEResponse(events, { splitMidFrame: true }))

    let final = null
    await streamChat('hi', 'en', 'ai', [], { onFinal: (evt) => (final = evt) })

    expect(final).not.toBeNull()
    expect(final.reply).toBe('ok')
  })

  it('sends the current message, lang, and an empty history in the request body', async () => {
    global.fetch.mockResolvedValue(
      makeSSEResponse([{ type: 'final', reply: '', matched_products: [], thinking_steps: [] }])
    )

    await streamChat('我想分析產能', 'zh', 'keyword', [], {})

    expect(global.fetch).toHaveBeenCalledWith(
      '/api/chat',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ message: '我想分析產能', lang: 'zh', mode: 'keyword', history: [] }),
      })
    )
  })

  it('sends prior turns as history when provided', async () => {
    global.fetch.mockResolvedValue(
      makeSSEResponse([{ type: 'final', reply: '', matched_products: [], thinking_steps: [] }])
    )
    const history = [
      { role: 'user', content: '我想要做一個 report' },
      { role: 'assistant', content: '可以說明一下想分析的報表主要跟哪個方向有關嗎？' },
    ]

    await streamChat('產能面的', 'zh', 'ai', history, {})

    expect(global.fetch).toHaveBeenCalledWith(
      '/api/chat',
      expect.objectContaining({
        body: JSON.stringify({ message: '產能面的', lang: 'zh', mode: 'ai', history }),
      })
    )
  })

  it('defaults history to an empty array when omitted', async () => {
    global.fetch.mockResolvedValue(
      makeSSEResponse([{ type: 'final', reply: '', matched_products: [], thinking_steps: [] }])
    )

    await streamChat('hi', 'en', 'ai', undefined, {})

    expect(global.fetch).toHaveBeenCalledWith(
      '/api/chat',
      expect.objectContaining({
        body: JSON.stringify({ message: 'hi', lang: 'en', mode: 'ai', history: [] }),
      })
    )
  })

  it('calls onError instead of throwing when the request fails', async () => {
    global.fetch.mockRejectedValue(new Error('network down'))

    let error = null
    await streamChat('hi', 'en', 'ai', [], { onError: (e) => (error = e) })

    expect(error).not.toBeNull()
    expect(error.message).toBe('network down')
  })

  it('calls onError when the response is not ok', async () => {
    global.fetch.mockResolvedValue({ ok: false, status: 500, body: null })

    let error = null
    await streamChat('hi', 'en', 'ai', [], { onError: (e) => (error = e) })

    expect(error).not.toBeNull()
  })

  it('omits user_key from the request body when not provided', async () => {
    global.fetch.mockResolvedValue(
      makeSSEResponse([{ type: 'final', reply: '', matched_products: [], thinking_steps: [] }])
    )

    await streamChat('hi', 'en', 'ai', [], {})

    expect(global.fetch).toHaveBeenCalledWith(
      '/api/chat',
      expect.objectContaining({
        body: JSON.stringify({ message: 'hi', lang: 'en', mode: 'ai', history: [] }),
      })
    )
  })

  it('includes user_key and user_token in the request body when provided', async () => {
    global.fetch.mockResolvedValue(
      makeSSEResponse([{ type: 'final', reply: '', matched_products: [], thinking_steps: [] }])
    )

    await streamChat('hi', 'en', 'ai', [], { userKey: 'tim@example.com', userToken: 'tim-token' })

    expect(global.fetch).toHaveBeenCalledWith(
      '/api/chat',
      expect.objectContaining({
        body: JSON.stringify({
          message: 'hi',
          lang: 'en',
          mode: 'ai',
          history: [],
          user_key: 'tim@example.com',
          user_token: 'tim-token',
        }),
      })
    )
  })
})

describe('getPreferences / clearPreferences', () => {
  beforeEach(() => {
    global.fetch = vi.fn()
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('getPreferences fetches the user-keyed list and sends the ownership token', async () => {
    global.fetch.mockResolvedValue({
      ok: true,
      json: async () => ({ preferences: ['usually asks about capacity data'] }),
    })

    const body = await getPreferences('tim@example.com', 'tim-token')

    expect(global.fetch).toHaveBeenCalledWith(
      '/api/preferences/tim%40example.com',
      expect.objectContaining({ headers: expect.objectContaining({ 'X-User-Token': 'tim-token' }) })
    )
    expect(body.preferences).toEqual(['usually asks about capacity data'])
  })

  it('clearPreferences sends a DELETE request with the ownership token', async () => {
    global.fetch.mockResolvedValue({ ok: true, json: async () => ({ status: 'success' }) })

    await clearPreferences('tim@example.com', 'tim-token')

    expect(global.fetch).toHaveBeenCalledWith(
      '/api/preferences/tim%40example.com',
      expect.objectContaining({
        method: 'DELETE',
        headers: expect.objectContaining({ 'X-User-Token': 'tim-token' }),
      })
    )
  })

  it('throws on a non-ok response', async () => {
    global.fetch.mockResolvedValue({ ok: false, status: 500 })
    await expect(getPreferences('tim@example.com', 'tim-token')).rejects.toThrow('HTTP 500')
  })
})

describe('queryProductData', () => {
  beforeEach(() => {
    global.fetch = vi.fn()
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('posts the question and returns the parsed rows', async () => {
    global.fetch.mockResolvedValue({
      ok: true,
      json: async () => ({ rows: [{ customer_name: 'Acme Semiconductor' }] }),
    })

    const body = await queryProductData('customer-capacity-allocation', 'which customers?')

    expect(global.fetch).toHaveBeenCalledWith(
      '/api/catalog/customer-capacity-allocation/query',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ question: 'which customers?' }),
      })
    )
    expect(body.rows).toEqual([{ customer_name: 'Acme Semiconductor' }])
  })

  it('throws with the backend detail message on a non-ok response', async () => {
    global.fetch.mockResolvedValue({
      ok: false,
      status: 400,
      json: async () => ({ detail: 'this product is not wired to a real data source' }),
    })

    await expect(queryProductData('other-product', 'x')).rejects.toThrow(
      'this product is not wired to a real data source'
    )
  })
})
