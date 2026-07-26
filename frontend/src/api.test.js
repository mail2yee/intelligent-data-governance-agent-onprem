import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { streamChat } from './api'

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
    await streamChat('hi', 'en', {
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
    await streamChat('hi', 'en', { onFinal: (evt) => (final = evt) })

    expect(final).not.toBeNull()
    expect(final.reply).toBe('ok')
  })

  it('sends the current message and lang in the request body', async () => {
    global.fetch.mockResolvedValue(
      makeSSEResponse([{ type: 'final', reply: '', matched_products: [], thinking_steps: [] }])
    )

    await streamChat('我想分析產能', 'zh', {})

    expect(global.fetch).toHaveBeenCalledWith(
      '/api/chat',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ message: '我想分析產能', lang: 'zh' }),
      })
    )
  })

  it('calls onError instead of throwing when the request fails', async () => {
    global.fetch.mockRejectedValue(new Error('network down'))

    let error = null
    await streamChat('hi', 'en', { onError: (e) => (error = e) })

    expect(error).not.toBeNull()
    expect(error.message).toBe('network down')
  })

  it('calls onError when the response is not ok', async () => {
    global.fetch.mockResolvedValue({ ok: false, status: 500, body: null })

    let error = null
    await streamChat('hi', 'en', { onError: (e) => (error = e) })

    expect(error).not.toBeNull()
  })
})
