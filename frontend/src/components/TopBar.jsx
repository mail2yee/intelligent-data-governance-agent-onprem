// Initials from a self-declared name/email (see ProfileDialog.jsx) - "?"
// when nothing's been set yet, never a hardcoded placeholder.
function initials(userKey) {
  const trimmed = (userKey || '').trim()
  if (!trimmed) return '?'
  const local = trimmed.split('@')[0]
  const parts = local.split(/[\s._-]+/).filter(Boolean)
  const chars = parts.length > 1 ? [parts[0][0], parts[1][0]] : [local[0]]
  return chars.join('').toUpperCase()
}

export default function TopBar({ t, userKey, onToggleLang, onToggleTheme, onOpenProfile }) {
  return (
    <header className="topbar">
      <div className="mark">DG</div>
      <div className="title">{t('appTitle')}</div>
      <span className="env-chip">{t('envChip')}</span>
      <div className="spacer"></div>
      <button className="icon-toggle lang-toggle" type="button" title="Switch language" onClick={onToggleLang}>
        中 / EN
      </button>
      <button className="icon-toggle" type="button" title="Toggle theme" onClick={onToggleTheme}>
        &#9680;
      </button>
      <button className="avatar" type="button" title={userKey || t('profileNotSet')} onClick={onOpenProfile}>
        {initials(userKey)}
      </button>
    </header>
  )
}
