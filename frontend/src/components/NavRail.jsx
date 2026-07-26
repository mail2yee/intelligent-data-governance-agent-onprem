import { useState } from 'react'

function Group({ label, children, defaultOpen = true }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <>
      <div className={`group-label${open ? '' : ' collapsed'}`} onClick={() => setOpen((o) => !o)}>
        <span>{label}</span>
        <span className="chev">&#9662;</span>
      </div>
      <div className={`group-items${open ? '' : ' collapsed'}`}>{children}</div>
    </>
  )
}

export default function NavRail({ t, view, onChangeView, pendingCount }) {
  return (
    <nav className="rail">
      <Group label={t('groupWorkspace')}>
        <button
          className={`nav-item${view === 'discover' ? ' active' : ''}`}
          type="button"
          onClick={() => onChangeView('discover')}
        >
          <span className="ic">&#128269;</span> {t('navDiscover')}
        </button>
        <button
          className={`nav-item${view === 'approvals' ? ' active' : ''}`}
          type="button"
          onClick={() => onChangeView('approvals')}
        >
          <span className="ic">&#128203;</span> {t('navApprovals')}
          <span className="count">{pendingCount}</span>
        </button>
      </Group>
      <Group label={t('groupAdmin')}>
        <button className="nav-item" type="button" disabled style={{ opacity: 0.5, cursor: 'default' }}>
          <span className="ic">&#128193;</span> {t('navCatalog')}
        </button>
      </Group>
    </nav>
  )
}
