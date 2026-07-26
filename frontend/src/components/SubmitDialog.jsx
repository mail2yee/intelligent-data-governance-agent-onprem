import { useState } from 'react'

export default function SubmitDialog({ t, open, cart, catalog, onCancel, onRemove, onSubmit }) {
  const [objective, setObjective] = useState('')
  const [purpose, setPurpose] = useState('PoC')

  if (!open) return null

  function submit() {
    if (!objective.trim()) {
      window.alert(t('objectiveRequired'))
      return
    }
    onSubmit(objective, purpose)
    setObjective('')
  }

  return (
    <div className="overlay show">
      <div className="dialog">
        <h2>{t('submitTitle')}</h2>
        <p className="sub">{t('submitSub')}</p>

        <div>
          {cart.map((id) => (
            <div className="cart-item" key={id}>
              <span>{catalog[id]?.name || id}</span>
              <button type="button" onClick={() => onRemove(id)}>
                &times;
              </button>
            </div>
          ))}
        </div>

        <label className="field-label">{t('objectiveLabel')}</label>
        <textarea
          placeholder={t('objectivePlaceholder')}
          value={objective}
          onChange={(e) => setObjective(e.target.value)}
        />

        <label className="field-label">{t('purposeLabel')}</label>
        <select value={purpose} onChange={(e) => setPurpose(e.target.value)}>
          <option value="PoC">{t('purposePoc')}</option>
          <option value="Production">{t('purposeProd')}</option>
        </select>

        <div className="dialog-actions">
          <button className="btn-secondary" type="button" onClick={onCancel}>
            {t('cancel')}
          </button>
          <button className="btn-primary" type="button" onClick={submit}>
            {t('submitBtn')}
          </button>
        </div>
      </div>
    </div>
  )
}
