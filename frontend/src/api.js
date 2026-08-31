// Thin fetch wrappers over the FastAPI backend. Routes differ slightly
// from the GCP PoC (cleaner REST now that there's no need to stay
// compatible with it) - see HANDOFF.md / backend/README.md for the map.

// X-API-Key, checked by backend/app/main.py's require_api_key against
// API_KEY in backend/.env - see that file's comment for what this does
// and doesn't cover. Baked in at build time by Vite (see
// docker-compose.yml's VITE_API_KEY build arg) - like any static SPA
// value, this is visible to anyone who opens devtools on the built JS,
// so it's a coarse gate against anonymous/external traffic, not a real
// secret from the browser's own perspective. Empty when VITE_API_KEY
// isn't set, matching the backend's "empty = auth disabled" default.
const API_KEY = import.meta.env.VITE_API_KEY || ''

function authHeaders(extra = {}) {
  return API_KEY ? { ...extra, 'X-API-Key': API_KEY } : extra
}

export async function getCatalog() {
  const res = await fetch('/api/catalog', { headers: authHeaders() })
  if (!res.ok) throw new Error('HTTP ' + res.status)
  return res.json()
}

export async function getConnectionMeta(productId) {
  const res = await fetch(`/api/catalog/${encodeURIComponent(productId)}/connection`, {
    headers: authHeaders(),
  })
  if (!res.ok) throw new Error('HTTP ' + res.status)
  return res.json()
}

// 2026-08-31: NL-to-SQL against a product's real business data (see
// backend/app/integrations/business_data.py's module docstring).
// Backend enforces both the registry-membership and approved-ticket
// gates server-side - a 400/403 here means one of those, not a network
// failure, so callers should surface res.json().detail rather than a
// generic error.
export async function queryProductData(productId, question) {
  const res = await fetch(`/api/catalog/${encodeURIComponent(productId)}/query`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ question }),
  })
  const body = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(body.detail || 'HTTP ' + res.status)
  return body
}

export async function createTicket({ products, objective, purpose }) {
  const res = await fetch('/api/tickets', {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ products, objective, purpose }),
  })
  if (!res.ok) throw new Error('HTTP ' + res.status)
  return res.json()
}

export async function getTickets() {
  const res = await fetch('/api/tickets', { headers: authHeaders() })
  if (!res.ok) throw new Error('HTTP ' + res.status)
  return res.json()
}

export async function submitApproval(ticketId, { owner_email, decision, reason }) {
  const res = await fetch(`/api/tickets/${encodeURIComponent(ticketId)}/approvals`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
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
//
// `history` (2026-08-31, prior {role, content} turns, oldest first) lets
// a follow-up message be interpreted together with what was already
// asked in this conversation instead of in isolation - see chat.py's
// run_chat() docstring for why this is a structural change (more
// context, same existing match/no-match decision), not a new LLM
// judgment call. Session-only on the caller's side - nothing here
// persists it, callers own deciding when a conversation resets.
export async function streamChat(message, lang, mode, history, { onStep, onToken, onFinal, onError } = {}) {
  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ message, lang, mode, history: history || [] }),
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
