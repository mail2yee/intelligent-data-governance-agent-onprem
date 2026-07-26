import { useRef, useState } from 'react'
import { streamChat } from '../api'
import ThinkingDots from './ThinkingDots'

let msgSeq = 0

export default function CopilotDock({ t, lang }) {
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
        setMessages([{ id: ++msgSeq, sender: 'bot', kind: 'html', html: t('copilotGreeting') }])
      }
      return next
    })
  }

  async function send() {
    const text = input.trim()
    if (!text) return
    setInput('')
    setMessages((prev) => [...prev, { id: ++msgSeq, sender: 'user', kind: 'html', html: text }])

    const botId = ++msgSeq
    setMessages((prev) => [...prev, { id: botId, sender: 'bot', kind: 'loading', steps: [], answer: '' }])
    scrollDown()

    let accumulated = ''
    await streamChat(text, lang, {
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
              {m.kind === 'html' && <span dangerouslySetInnerHTML={{ __html: m.html }} />}
              {m.kind === 'loading' && <ThinkingDots label={t('thinking')} />}
              {m.kind === 'error' && t('toastFailed')}
              {m.kind === 'streaming' && (
                <>
                  {m.steps.map((s, i) => (
                    <div className="copilot-step" key={i}>
                      {s}
                    </div>
                  ))}
                  {m.answer && <div className="copilot-answer" dangerouslySetInnerHTML={{ __html: m.answer }} />}
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
