import { useEffect, useState } from 'react'
import { getConnectionMeta, queryProductData } from '../api'

function pythonSnippet(meta) {
  return [
    'import pandas as pd',
    'from sqlalchemy import create_engine',
    '',
    `DB_HOST = "${meta.db_host}"`,
    `DB_PORT = "${meta.db_port}"`,
    `DB_SCHEMA = "${meta.db_schema}"`,
    '# pull the real credential from Secret Manager, do not hardcode it',
    '',
    'engine = create_engine(f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/warehouse")',
    'df = pd.read_sql(f"SELECT * FROM {DB_SCHEMA}.summarized_data LIMIT 100", engine)',
  ].join('\n')
}

function javaSnippet(meta) {
  return [
    `String dbUrl = "jdbc:postgresql://${meta.db_host}:${meta.db_port}/warehouse";`,
    '// pull the real credential from Secret Manager, do not hardcode it',
    'Connection conn = DriverManager.getConnection(dbUrl, user, pass);',
    'Statement stmt = conn.createStatement();',
    `ResultSet rs = stmt.executeQuery("SELECT * FROM ${meta.db_schema}.summarized_data LIMIT 10");`,
  ].join('\n')
}

export default function ConnectionCodeDialog({ t, productId, onClose }) {
  const [meta, setMeta] = useState(null)
  const [lang, setLang] = useState('python')
  const [question, setQuestion] = useState('')
  const [queryState, setQueryState] = useState({ status: 'idle', rows: null, message: '' })

  useEffect(() => {
    if (!productId) return
    setLang('python')
    setQuestion('')
    setQueryState({ status: 'idle', rows: null, message: '' })
    getConnectionMeta(productId)
      .then(setMeta)
      .catch(() => setMeta(null))
  }, [productId])

  if (!productId) return null

  async function runQuery() {
    if (!question.trim()) return
    setQueryState({ status: 'loading', rows: null, message: '' })
    try {
      const body = await queryProductData(productId, question.trim())
      if (!body.rows || body.rows.length === 0) {
        setQueryState({ status: 'empty', rows: [], message: body.message || t('queryEmpty') })
      } else {
        setQueryState({ status: 'done', rows: body.rows, message: '' })
      }
    } catch (e) {
      // /query returns 400 for a product not in PRODUCT_DATA_SOURCES
      // (see backend/app/integrations/business_data.py) - surface that
      // as "not wired" rather than a generic failure, it's an expected
      // state for the two catalog products that aren't real yet.
      const notWired = String(e.message || '').includes('not wired')
      setQueryState({
        status: 'error',
        rows: null,
        message: notWired ? t('queryNotWired') : t('queryFailed'),
      })
    }
  }

  return (
    <div className="overlay show">
      <div className="dialog">
        <h2>{t('codeTitle')}</h2>
        <p className="sub">{t('codeSub')}</p>
        <div className="code-tabs">
          <button
            className={`code-tab${lang === 'python' ? ' active' : ''}`}
            type="button"
            onClick={() => setLang('python')}
          >
            Python
          </button>
          <button
            className={`code-tab${lang === 'java' ? ' active' : ''}`}
            type="button"
            onClick={() => setLang('java')}
          >
            Java
          </button>
        </div>
        <div className="code-block mono">
          {meta ? (lang === 'python' ? pythonSnippet(meta) : javaSnippet(meta)) : '…'}
        </div>
        <div className="query-panel">
          <div className="field-label">{t('queryTitle')}</div>
          <div className="query-row">
            <input
              type="text"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && runQuery()}
              placeholder={t('queryPlaceholder')}
            />
            <button
              className="btn-secondary"
              type="button"
              onClick={runQuery}
              disabled={queryState.status === 'loading' || !question.trim()}
            >
              {t('queryBtn')}
            </button>
          </div>
          {queryState.status === 'loading' && <p className="sub">{t('thinking')}…</p>}
          {(queryState.status === 'empty' || queryState.status === 'error') && (
            <p className={queryState.status === 'error' ? 'sub query-error' : 'sub'}>
              {queryState.message}
            </p>
          )}
          {queryState.status === 'done' && queryState.rows && (
            <div className="query-result">
              <div className="query-result-wrap">
                <table>
                  <thead>
                    <tr>
                      {Object.keys(queryState.rows[0]).map((col) => (
                        <th key={col}>{col}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {queryState.rows.map((row, i) => (
                      <tr key={i}>
                        {Object.keys(queryState.rows[0]).map((col) => (
                          <td key={col}>{String(row[col])}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
        <div className="dialog-actions">
          <button className="btn-secondary" type="button" onClick={onClose}>
            {t('close')}
          </button>
        </div>
      </div>
    </div>
  )
}
