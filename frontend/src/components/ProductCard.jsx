export default function ProductCard({ product, inCart, onToggleCart, t }) {
  const maturityClass = product.maturity_level === 'Gold' ? 'gold' : 'silver'
  return (
    <div className="product-card">
      <div className="head">
        <div>
          <div className="pid mono">{product.id}</div>
          <h3>{product.name}</h3>
        </div>
        <span className={`maturity-chip ${maturityClass}`}>{product.maturity_level}</span>
      </div>
      <p className="desc">{product.description}</p>
      <div className="kv-grid">
        <div>
          <div className="k">{t('qualityScore')}</div>
          <div className="v">{product.data_quality_score}</div>
        </div>
        <div>
          <div className="k">{t('updateFreq')}</div>
          <div className="v">{product.frequency}</div>
        </div>
        <div className="full">
          <div className="k">{t('relatedTables')}</div>
          <div className="v mono" style={{ fontWeight: 500 }}>
            {product.tables_joined}
          </div>
        </div>
        <div className="full">
          <div className="k">{t('dataOwner')}</div>
          <div className="v mono" style={{ fontWeight: 500 }}>
            {product.owner}
          </div>
        </div>
      </div>
      <button className={`btn-add${inCart ? ' added' : ''}`} type="button" onClick={() => onToggleCart(product.id)}>
        {inCart ? t('addedToCart') : t('addToCart')}
      </button>
    </div>
  )
}
