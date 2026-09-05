import { useEffect, useState } from 'react'
import { clearPreferences, getPreferences } from '../api'

export default function ProfileDialog({ t, open, userKey, userToken, onSave, onClose }) {
  const [name, setName] = useState(userKey || '')
  const [preferences, setPreferences] = useState([])

  useEffect(() => {
    if (!open) return
    setName(userKey || '')
    if (!userKey) {
      setPreferences([])
      return
    }
    getPreferences(userKey, userToken)
      .then((body) => setPreferences(body.preferences || []))
      .catch(() => setPreferences([]))
  }, [open, userKey, userToken])

  if (!open) return null

  function save() {
    onSave(name.trim())
  }

  async function clear() {
    if (!userKey) return
    await clearPreferences(userKey, userToken).catch(() => {})
    setPreferences([])
  }

  return (
    <div className="overlay show">
      <div className="dialog">
        <h2>{t('profileTitle')}</h2>
        <p className="sub">{t('profileSub')}</p>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && save()}
          placeholder={t('profileNamePlaceholder')}
        />

        <div className="field-label">{t('profilePreferencesTitle')}</div>
        {preferences.length === 0 ? (
          <p className="sub">{t('profilePreferencesEmpty')}</p>
        ) : (
          <ul className="preference-list">
            {preferences.map((p, i) => (
              <li key={i}>{p}</li>
            ))}
          </ul>
        )}
        {preferences.length > 0 && (
          <button className="btn-secondary" type="button" onClick={clear}>
            {t('profileClear')}
          </button>
        )}

        <div className="dialog-actions">
          <button className="btn-secondary" type="button" onClick={onClose}>
            {t('close')}
          </button>
          <button className="btn-primary" type="button" onClick={save}>
            {t('profileSave')}
          </button>
        </div>
      </div>
    </div>
  )
}
