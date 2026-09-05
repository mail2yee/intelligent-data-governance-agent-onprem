import { useEffect, useRef, useState } from 'react'
import './App.css'
import { createTicket, getCatalog, getTickets, submitApproval } from './api'
import ApprovalsView from './components/ApprovalsView'
import CartBar from './components/CartBar'
import ConnectionCodeDialog from './components/ConnectionCodeDialog'
import CopilotDock from './components/CopilotDock'
import DiscoverView from './components/DiscoverView'
import NavRail from './components/NavRail'
import ProfileDialog from './components/ProfileDialog'
import SubmitDialog from './components/SubmitDialog'
import Toast from './components/Toast'
import TopBar from './components/TopBar'
import { makeT } from './i18n'

// Lightweight, self-declared identity (see ProfileDialog.jsx / HANDOFF.md
// "Personal chat preference memory") - not a real login, just a name/email
// the browser remembers so the backend can key preferences by it across
// sessions. Same persisted-in-localStorage pattern as DiscoverView's
// search-mode toggle.
const USER_KEY_STORAGE = 'dgo_user_key'

// A random per-browser token, generated once and kept forever (unlike
// USER_KEY_STORAGE, this never changes even if the displayed name does)
// - see backend/app/identity.py's module docstring. Trust-on-first-use:
// the backend remembers whichever token first claimed a given user_key
// and rejects any other token claiming the same one afterward, so this
// is what actually proves "the same browser that set up this name is
// the one asking again" for preferences and ticket approvals - not real
// authentication, but enough to stop one person acting as another just
// by knowing/guessing their name or email.
const USER_TOKEN_STORAGE = 'dgo_user_token'

function loadOrCreateUserToken() {
  let token = localStorage.getItem(USER_TOKEN_STORAGE)
  if (!token) {
    token = crypto.randomUUID()
    localStorage.setItem(USER_TOKEN_STORAGE, token)
  }
  return token
}

function App() {
  const [lang, setLang] = useState('zh')
  const [theme, setTheme] = useState('light')
  const [view, setView] = useState('discover')
  const [catalog, setCatalog] = useState({})
  const [cart, setCart] = useState([])
  const [tickets, setTickets] = useState([])
  const [submitOpen, setSubmitOpen] = useState(false)
  const [codeProductId, setCodeProductId] = useState(null)
  const [toast, setToast] = useState({ message: '', visible: false })
  const [userKey, setUserKey] = useState(() => localStorage.getItem(USER_KEY_STORAGE) || '')
  const [userToken] = useState(loadOrCreateUserToken)
  const [profileOpen, setProfileOpen] = useState(false)
  const toastTimer = useRef(null)

  const t = makeT(lang)

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
  }, [theme])

  useEffect(() => {
    document.documentElement.lang = lang === 'zh' ? 'zh-Hant' : 'en'
  }, [lang])

  useEffect(() => {
    getCatalog()
      .then(setCatalog)
      .catch((e) => console.error('[DGO] getCatalog failed:', e))
    refreshTickets()
  }, [])

  function refreshTickets() {
    getTickets()
      .then((data) => {
        setTickets(data)
        console.log('[DGO] loadTickets:', data.length, 'ticket(s)')
      })
      .catch((e) => {
        console.error('[DGO] loadTickets failed:', e)
        setTickets([])
      })
  }

  function changeView(next) {
    setView(next)
    if (next === 'approvals') refreshTickets()
  }

  function showToast(message) {
    setToast({ message, visible: true })
    clearTimeout(toastTimer.current)
    toastTimer.current = setTimeout(() => setToast((s) => ({ ...s, visible: false })), 3200)
  }

  function toggleCart(id) {
    setCart((prev) => {
      const next = prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
      console.log('[DGO] cart ->', next)
      return next
    })
  }

  async function handleSubmitTicket(objective, purpose) {
    try {
      const data = await createTicket({ products: cart, objective, purpose })
      console.log('[DGO] create-ticket response:', data)
      setCart([])
      setSubmitOpen(false)
      showToast(t('toastSubmitted')(data.ticket_id))
      refreshTickets()
    } catch (e) {
      console.error('[DGO] create-ticket failed:', e)
      showToast(t('toastFailed'))
    }
  }

  async function handleApprove(ticketId, email, decision, reason) {
    console.log('[DGO] submit-approval:', ticketId, email, decision)
    try {
      await submitApproval(ticketId, {
        owner_email: email,
        decision,
        reason,
        user_key: userKey,
        user_token: userToken,
      })
    } catch (e) {
      console.error('[DGO] submit-approval failed:', e)
      showToast(t('toastFailed'))
    }
    refreshTickets()
  }

  function saveUserKey(next) {
    setUserKey(next)
    if (next) localStorage.setItem(USER_KEY_STORAGE, next)
    else localStorage.removeItem(USER_KEY_STORAGE)
    setProfileOpen(false)
  }

  const pendingCount = tickets.filter((tk) => tk.status === 'PENDING_APPROVAL').length

  return (
    <div className="shell">
      <TopBar
        t={t}
        userKey={userKey}
        onToggleLang={() => setLang((l) => (l === 'zh' ? 'en' : 'zh'))}
        onToggleTheme={() => setTheme((th) => (th === 'dark' ? 'light' : 'dark'))}
        onOpenProfile={() => setProfileOpen(true)}
      />

      <NavRail t={t} view={view} onChangeView={changeView} pendingCount={pendingCount} />

      <main className="main">
        {view === 'discover' && (
          <DiscoverView
            t={t}
            lang={lang}
            catalog={catalog}
            cart={cart}
            onToggleCart={toggleCart}
            userKey={userKey}
            userToken={userToken}
          />
        )}
        {view === 'approvals' && (
          <ApprovalsView
            t={t}
            tickets={tickets}
            userKey={userKey}
            onApprove={handleApprove}
            onShowCode={setCodeProductId}
          />
        )}
      </main>

      <CartBar t={t} cart={cart} onReview={() => setSubmitOpen(true)} />

      <CopilotDock t={t} lang={lang} userKey={userKey} userToken={userToken} />

      <SubmitDialog
        t={t}
        open={submitOpen}
        cart={cart}
        catalog={catalog}
        onCancel={() => setSubmitOpen(false)}
        onRemove={toggleCart}
        onSubmit={handleSubmitTicket}
      />

      <ConnectionCodeDialog t={t} productId={codeProductId} onClose={() => setCodeProductId(null)} />

      <ProfileDialog
        t={t}
        open={profileOpen}
        userKey={userKey}
        userToken={userToken}
        onSave={saveUserKey}
        onClose={() => setProfileOpen(false)}
      />

      <Toast message={toast.message} visible={toast.visible} />
    </div>
  )
}

export default App
