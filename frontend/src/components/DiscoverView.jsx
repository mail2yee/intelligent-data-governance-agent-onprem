import { useState } from 'react'
import { streamChat } from '../api'
import ProductCard from './ProductCard'
import ThinkingDots from './ThinkingDots'

const CHIPS = [
  { key: 'chip1', qZh: '特定客戶產能與生產 Move 預估', qEn: 'specific customer capacity and production move forecast' },
  { key: 'chip2', qZh: '全球客戶投片訂單與需求排程', qEn: 'global customer wafer order demand schedule' },
  { key: 'chip3', qZh: '員工薪資查詢', qEn: 'employee salary lookup' },
]

// Persisted like lang/theme - a search-mode preference, not a per-query
// setting (see the 2026-07-31 design discussion: default to plain
// keyword search, same as Google's "AI Mode" toggle pattern).
const SEARCH_MODE_KEY = 'dgo_search_mode'

export default function DiscoverView({ t, lang, catalog, cart, onToggleCart }) {
  const [query, setQuery] = useState('')
  const [mode, setMode] = useState(() => {
    const saved = localStorage.getItem(SEARCH_MODE_KEY)
    return saved === 'ai' ? 'ai' : 'keyword'
  })
  const [phase, setPhase] = useState('idle') // idle | loading | done | empty | error
  const [note, setNote] = useState('')
  const [hits, setHits] = useState([])
  const [steps, setSteps] = useState([])
  const [stepsOpen, setStepsOpen] = useState(false)

  function selectMode(next) {
    setMode(next)
    localStorage.setItem(SEARCH_MODE_KEY, next)
  }

  async function runSearch(q) {
    if (!q.trim()) {
      setPhase('idle')
      return
    }
    console.log('[DGO] runSearch:', q, 'mode:', mode)
    setPhase('loading')
    setNote('')
    setHits([])
    setSteps([])
    setStepsOpen(true) // auto-expand live while steps are actually arriving

    let accumulated = ''
    await streamChat(q, lang, mode, {
      onStep: (text) => setSteps((prev) => [...prev, text]),
      onToken: (text) => {
        accumulated += text
        setNote(accumulated)
      },
      onFinal: (evt) => {
        const matched = (evt.matched_products || []).filter((id) => catalog[id])
        const finalReply = evt.reply || accumulated
        // Reply text always ends up in `note` (rendered in the same spot
        // whether or not anything matched) so it doesn't visually jump
        // from the streaming position to a different "empty state" box
        // once the final event decides there's no match.
        setNote(finalReply || t('emptyState')(q))
        setHits(matched)
        setPhase(matched.length === 0 ? 'empty' : 'done')
      },
      onError: () => setPhase('error'),
    })
  }

  return (
    <section className="view active">
      <div className="search-hero">
        <h1>{t('discoverH1')}</h1>
        <p className="lead" style={{ textAlign: 'center' }}>
          {t('discoverLead')}
        </p>
        <div className="search-box">
          <span>&#128269;</span>
          <input
            type="text"
            placeholder={t('searchPlaceholder')}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') runSearch(query)
            }}
          />
          <button type="button" onClick={() => runSearch(query)}>
            {t('searchBtn')}
          </button>
        </div>
        <div className="search-mode-toggle" role="group">
          <button
            type="button"
            className={`mode-pill${mode === 'keyword' ? ' active' : ''}`}
            onClick={() => selectMode('keyword')}
          >
            {t('searchModeKeyword')}
          </button>
          <button
            type="button"
            className={`mode-pill${mode === 'ai' ? ' active' : ''}`}
            onClick={() => selectMode('ai')}
          >
            {t('searchModeAi')}
          </button>
        </div>
        <div className="chips">
          {CHIPS.map((c) => (
            <button
              key={c.key}
              className="chip"
              type="button"
              onClick={() => {
                const q = lang === 'zh' ? c.qZh : c.qEn
                setQuery(q)
                runSearch(q)
              }}
            >
              {t(c.key)}
            </button>
          ))}
        </div>
      </div>

      {phase !== 'idle' && (
        <div>
          {(phase === 'done' || phase === 'loading' || phase === 'empty') && note && (
            <div className="assistant-note">{note}</div>
          )}

          <p className="results-meta">
            {phase === 'loading' && <ThinkingDots label={t('thinking')} />}
            {phase === 'done' && t('resultsMeta')(hits.length)}
          </p>

          {steps.length > 0 && (
            <div>
              <button
                className={`thinking-toggle${stepsOpen ? ' open' : ''}`}
                type="button"
                onClick={() => setStepsOpen((o) => !o)}
              >
                <span className="chev">&#9656;</span> {t('showThinking')}
              </button>
              <div className={`thinking-steps${stepsOpen ? ' open' : ''}`}>
                {steps.map((s, i) => (
                  <div className="step" key={i}>
                    {s}
                  </div>
                ))}
              </div>
            </div>
          )}

          {phase === 'error' && <div className="empty-state">{t('toastFailed')}</div>}

          {phase === 'done' && (
            <div className="card-grid">
              {hits.map((id) => (
                <ProductCard
                  key={id}
                  product={catalog[id]}
                  inCart={cart.includes(id)}
                  onToggleCart={onToggleCart}
                  t={t}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  )
}
