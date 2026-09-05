import { approvalHours } from '../utils'
import TicketRow from './TicketRow'

function slaStats(tickets) {
  const pending = tickets.filter((t) => t.status === 'PENDING_APPROVAL')

  let worstOwner = null
  let worstHours = -1
  const byOwner = {}
  pending.forEach((tk) => {
    ;(tk.owners || []).forEach((email) => {
      const a = tk.approvals?.[email] || { decision: 'PENDING' }
      if (a.decision !== 'PENDING') return
      const h = approvalHours(a)
      byOwner[email] = byOwner[email] || []
      byOwner[email].push(h)
    })
  })
  Object.keys(byOwner).forEach((email) => {
    const avg = byOwner[email].reduce((a, b) => a + b, 0) / byOwner[email].length
    if (avg > worstHours) {
      worstHours = avg
      worstOwner = email
    }
  })

  const allHours = []
  tickets.forEach((tk) =>
    Object.values(tk.approvals || {}).forEach((a) => {
      if (a.cycle_time_seconds) allHours.push(a.cycle_time_seconds / 3600)
    })
  )
  const avgAll = allHours.length ? allHours.reduce((a, b) => a + b, 0) / allHours.length : 0

  return {
    pendingCount: pending.length,
    total: tickets.length,
    worstOwner,
    worstHours,
    avgAll,
    hasAvg: allHours.length > 0,
  }
}

export default function ApprovalsView({ t, tickets, userKey, onApprove, onShowCode }) {
  const stats = slaStats(tickets)

  return (
    <section className="view active">
      <h1>{t('navApprovals')}</h1>
      <p className="lead">{t('approvalsLead')}</p>
      <p className="sub">{t('approvalsIdentityHint')}</p>

      <div className="sla-strip">
        <div className="sla-stat">
          <div className="label">{t('slaPending')}</div>
          <div className="value">{stats.pendingCount}</div>
          <div className="sub">{t('pendingSub')(stats.total)}</div>
        </div>
        <div className="sla-stat">
          <div className="label">{t('slaSlowest')}</div>
          <div className="value crit">{stats.worstOwner ? stats.worstOwner.split('@')[0] : '—'}</div>
          <div className="sub">{stats.worstOwner ? t('slowestSub')(stats.worstHours.toFixed(1)) : ''}</div>
        </div>
        <div className="sla-stat">
          <div className="label">{t('slaAvg')}</div>
          <div className="value mono">{stats.hasAvg ? stats.avgAll.toFixed(1) : '—'}</div>
          <div className="sub">{stats.hasAvg ? t('avgSub')(stats.avgAll.toFixed(1)) : ''}</div>
        </div>
      </div>

      <div className="ticket-list">
        {tickets.length === 0 ? (
          <div className="empty-state">{t('noTickets')}</div>
        ) : (
          tickets.map((ticket) => (
            <TicketRow
              key={ticket.id}
              ticket={ticket}
              t={t}
              userKey={userKey}
              onApprove={onApprove}
              onShowCode={onShowCode}
            />
          ))
        )}
      </div>
    </section>
  )
}
