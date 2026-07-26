export default function CartBar({ t, cart, onReview }) {
  return (
    <div className={`cart-bar${cart.length > 0 ? ' show' : ''}`}>
      <span className="count">{t('cartCount')(cart.length)}</span>
      <div className="spacer"></div>
      <button className="btn-primary" type="button" onClick={onReview}>
        {t('reviewCart')}
      </button>
    </div>
  )
}
