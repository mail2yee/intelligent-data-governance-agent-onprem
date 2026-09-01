import { useRef, useState } from 'react'
import { streamChat } from '../api'
import ThinkingDots from './ThinkingDots'

let msgSeq = 0

export default function CopilotDock({ t, lang, userKey }) {
  const [open, setOpen] = useState(false)
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const bodyRef = useRef(null)

  function scrollDown() {
    requestAnimationFrame(() => {
      if (bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight
    })
  }

  function toggle() {
    setOpen((wasOpen) => {
      const next = !wasOpen
      if (next && messages.length === 0) {
        setMessages([{ id: ++msgSeq, sender: 'bot', kind: 'text', text: t('copilotGreeting') }])
      }
      return next
    })
  }

  async function send() {
    const text = input.trim()
    if (!text) return
    // Built from `messages` BEFORE this turn's own updates below, so it's
    // exactly what the conversation looked like up to (not including)
    // the message being sent now - see chat.py's run_chat() docstring
    // for what the backend does with this. Deliberately excludes the
    // canned greeting (kind: 'text' from the bot, not a real reply) and
    // any errored turn (kind: 'error', no real answer to hand back) -
    // only genuine user/assistant exchanges belong in the LLM's context.
    const history = messages
      .filter(
        (m) =>
          (m.sender === 'user' && m.kind === 'text') || (m.sender === 'bot' && m.kind === 'streaming' && m.answer)
      )
      .map((m) => ({
        role: m.sender === 'user' ? 'user' : 'assistant',
        content: m.sender === 'user' ? m.text : m.answer,
      }))

    setInput('')
    setMessages((prev) => [...prev, { id: ++msgSeq, sender: 'user', kind: 'text', text }])

    const botId = ++msgSeq
    setMessages((prev) => [...prev, { id: botId, sender: 'bot', kind: 'loading', steps: [], answer: '' }])
    scrollDown()

    let accumulated = ''
    // Always AI mode here - the assistant dock is inherently conversational
    // (see DiscoverView.jsx for the general/AI search toggle, which only
    // applies to the Discover search box, not this chat panel).
    await streamChat(text, lang, 'ai', history, {
      userKey,
      onStep: (stepText) => {
        setMessages((prev) =>
          prev.map((m) => (m.id === botId ? { ...m, kind: 'streaming', steps: [...m.steps, stepText] } : m))
        )
        scrollDown()
      },
      onToken: (tokenText) => {
        accumulated += tokenText
        setMessages((prev) =>
          prev.map((m) => (m.id === botId ? { ...m, kind: 'streaming', answer: accumulated } : m))
        )
        scrollDown()
      },
      onFinal: (evt) => {
        setMessages((prev) =>
          prev.map((m) => (m.id === botId ? { ...m, kind: 'streaming', answer: evt.reply || accumulated } : m))
        )
        scrollDown()
      },
      onError: () => {
        setMessages((prev) => prev.map((m) => (m.id === botId ? { ...m, kind: 'error' } : m)))
      },
    })
  }

  return (
    <div className="copilot-dock">
      <div className={`copilot-panel${open ? ' open' : ''}`}>
        <div className="copilot-head">
          <div className="ic">DG</div>
          <div>
            <div className="name">{t('copilotName')}</div>
            <div className="desc">{t('copilotDesc')}</div>
          </div>
        </div>
        <div className="copilot-body" ref={bodyRef}>
          {messages.map((m) => (
            <div className={`copilot-msg ${m.sender}`} key={m.id}>
              {m.kind === 'text' && <span>{m.text}</span>}
              {m.kind === 'loading' && <ThinkingDots label={t('thinking')} />}
              {m.kind === 'error' && t('toastFailed')}
              {m.kind === 'streaming' && (
                <>
                  {m.steps.map((s, i) => (
                    <div className="copilot-step" key={i}>
                      {s}
                    </div>
                  ))}
                  {m.answer && <div className="copilot-answer">{m.answer}</div>}
                </>
              )}
            </div>
          ))}
        </div>
        <div className="copilot-input-row">
          <input
            type="text"
            placeholder={t('copilotInputPlaceholder')}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') send()
            }}
          />
          <button className="btn-primary" type="button" onClick={send}>
            {t('copilotSend')}
          </button>
        </div>
      </div>
      <button className="copilot-fab" type="button" onClick={toggle}>
        <span className="dot"></span> {t('copilotFabLabel')}
      </button>
    </div>
  )
}
