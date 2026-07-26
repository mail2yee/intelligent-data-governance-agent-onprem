export default function TopBar({ t, onToggleLang, onToggleTheme }) {
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
      <div className="avatar">TS</div>
    </header>
  )
}
