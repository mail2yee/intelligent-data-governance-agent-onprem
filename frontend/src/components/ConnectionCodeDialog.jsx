import { useEffect, useState } from 'react'
import { getConnectionMeta } from '../api'

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

  useEffect(() => {
    if (!productId) return
    setLang('python')
    getConnectionMeta(productId)
      .then(setMeta)
      .catch(() => setMeta(null))
  }, [productId])

  if (!productId) return null

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
        <div className="dialog-actions">
          <button className="btn-secondary" type="button" onClick={onClose}>
            {t('close')}
          </button>
        </div>
      </div>
    </div>
  )
}
