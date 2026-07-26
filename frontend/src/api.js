// Thin fetch wrappers over the FastAPI backend. Routes differ slightly
// from the GCP PoC (cleaner REST now that there's no need to stay
// compatible with it) - see HANDOFF.md / backend/README.md for the map.

export async function getCatalog() {
  const res = await fetch('/api/catalog')
  if (!res.ok) throw new Error('HTTP ' + res.status)
  return res.json()
}

export async function getConnectionMeta(productId) {
  const res = await fetch(`/api/catalog/${encodeURIComponent(productId)}/connection`)
  if (!res.ok) throw new Error('HTTP ' + res.status)
  return res.json()
}

export async function createTicket({ products, objective, purpose }) {
  const res = await fetch('/api/tickets', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ products, objective, purpose }),
  })
  if (!res.ok) throw new Error('HTTP ' + res.status)
  return res.json()
}

export async function getTickets() {
  const res = await fetch('/api/tickets')
  if (!res.ok) throw new Error('HTTP ' + res.status)
  return res.json()
}

export async function submitApproval(ticketId, { owner_email, decision, reason }) {
  const res = await fetch(`/api/tickets/${encodeURIComponent(ticketId)}/approvals`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ owner_email, decision, reason }),
  })
  if (!res.ok) throw new Error('HTTP ' + res.status)
  return res.json()
}

// Reads the /api/chat SSE stream and dispatches step / token / final /
// error callbacks as events arrive, so callers can render progressively
// instead of waiting for one big JSON blob. Ported from the PoC's
// streamChat() - see HANDOFF.md "Chat / search assistant" for why this
// has to be a real stream, not a fake staggered reveal.
export async function streamChat(message, lang, { onStep, onToken, onFinal, onError } = {}) {
  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, lang }),
    })
    if (!res.ok || !res.body) throw new Error('HTTP ' + res.status)
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const parts = buffer.split('\n\n')
      buffer = parts.pop()
      for (const part of parts) {
        const line = part.trim()
        if (!line.startsWith('data:')) continue
        let evt
        try {
          evt = JSON.parse(line.slice(5).trim())
        } catch {
          continue
        }
        if (evt.type === 'step' && onStep) onStep(evt.text)
        else if (evt.type === 'token' && onToken) onToken(evt.text)
        else if (evt.type === 'final' && onFinal) onFinal(evt)
      }
    }
  } catch (e) {
    console.error('[DGO] streamChat failed:', e)
    if (onError) onError(e)
  }
}
