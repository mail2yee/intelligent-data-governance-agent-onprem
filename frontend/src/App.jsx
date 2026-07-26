import { useEffect, useState } from 'react'
import './App.css'

// This is a connectivity-proving skeleton, not a port of the PoC's full
// UI yet - see HANDOFF.md "UI/UX direction" for what the real Discover /
// Approvals / Copilot screens should look like when built out.
function App() {
  const [health, setHealth] = useState('checking')
  const [catalog, setCatalog] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', 'light')
  }, [])

  useEffect(() => {
    fetch('/health')
      .then((res) => (res.ok ? setHealth('ok') : setHealth('down')))
      .catch(() => setHealth('down'))

    fetch('/api/catalog')
      .then((res) => res.json())
      .then((data) => setCatalog(data))
      .catch((e) => setError(String(e)))
  }, [])

  const products = catalog ? Object.values(catalog) : []

  return (
    <div>
      <header className="topbar">
        <div className="mark">DG</div>
        <div className="title">智慧資料治理平台</div>
        <span className="env-chip">On-Prem Scaffold</span>
        <div className="spacer"></div>
        <div className="status">
          <span className={`dot ${health === 'ok' ? 'ok' : 'down'}`}></span>
          backend: {health}
        </div>
      </header>

      <main className="main">
        <h1 style={{ fontSize: 20, fontWeight: 500 }}>資料目錄（來自後端 /api/catalog）</h1>
        {error && <div className="empty-state">連線失敗：{error}</div>}
        {!error && products.length === 0 && <div className="empty-state">載入中…</div>}
        <div className="card-grid">
          {products.map((p) => (
            <div className="product-card" key={p.id}>
              <div className="pid mono">{p.id}</div>
              <h3>{p.name}</h3>
              <span className="maturity-chip">{p.maturity_level}</span>
              <p>{p.description}</p>
            </div>
          ))}
        </div>
      </main>
    </div>
  )
}

export default App
