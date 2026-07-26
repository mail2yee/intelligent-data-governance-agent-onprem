import { useState } from 'react'
import { initials, approvalHours } from '../utils'

function statusChipClass(status) {
  if (status === 'APPROVED') return 'approved'
  if (status === 'REJECTED') return 'rejected'
  return 'pending'
}
function statusLabel(status, t) {
  if (status === 'APPROVED') return t('statusApproved')
  if (status === 'REJECTED') return t('statusRejected')
  return t('statusPending')
}

export default function TicketRow({ ticket, t, onApprove, onShowCode }) {
  const [open, setOpen] = useState(false)
  const owners = ticket.owners || []
  const approvals = owners.map((email) => ({
    email,
    ...(ticket.approvals?.[email] || { decision: 'PENDING' }),
  }))

  let worst = null
  approvals.forEach((a) => {
    const h = approvalHours(a)
    if (a.decision === 'PENDING' && (!worst || h > worst.hours)) worst = { email: a.email, hours: h }
  })
  const slaBreach = ticket.status === 'PENDING_APPROVAL' && worst && worst.hours > 24

  function reject(email) {
    const reason = window.prompt(t('rejectPrompt')) || ''
    if (!reason) {
      window.alert(t('rejectRequired'))
      return
    }
    onApprove(ticket.id, email, 'Reject', reason)
  }

  return (
    <div className={`ticket-row${open ? ' open' : ''}`}>
      <div className="ticket-summary" onClick={() => setOpen((o) => !o)}>
        <span className="chevron">&#9656;</span>
        <span className="id mono">{ticket.id}</span>
        <span className="products">
          {(ticket.products || []).join(', ')} · {ticket.purpose}
        </span>
        <div className="avatars">
          {owners.map((e) => (
            <div className="av" key={e}>
              {initials(e)}
            </div>
          ))}
        </div>
        <span className={`status-chip ${statusChipClass(ticket.status)}`}>{statusLabel(ticket.status, t)}</span>
      </div>

      <div className="ticket-detail">
        <p className="objective">
          <b>{t('objectivePrefix')}</b>
          {ticket.objective}
        </p>

        {slaBreach && (
          <div className="sla-banner">{t('slaBanner')(worst.email.split('@')[0], worst.hours.toFixed(1))}</div>
        )}

        {approvals.map((a) => (
          <div className="approver-row" key={a.email}>
            <div className="av">{initials(a.email)}</div>
            <div className="who">
              <div className="email mono">{a.email}</div>
              <div className="time">
                {a.decision === 'PENDING' ? t('notReviewed') : t('decidedLine')(a.decision, approvalHours(a).toFixed(1))}
              </div>
              {a.reason && (
                <div className="reason">
                  {t('rejectReasonPrefix')}
                  {a.reason}
                </div>
              )}
            </div>
            {a.decision === 'PENDING' && (
              <div className="actions">
                <button
                  className="btn-mini approve"
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation()
                    onApprove(ticket.id, a.email, 'Approve', '')
                  }}
                >
                  {t('approveLabel')}
                </button>
                <button
                  className="btn-mini reject"
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation()
                    reject(a.email)
                  }}
                >
                  {t('rejectLabel')}
                </button>
              </div>
            )}
          </div>
        ))}

        {ticket.status === 'APPROVED' && (
          <div style={{ marginTop: 10 }}>
            <button
              className="code-link"
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                onShowCode((ticket.products || [])[0])
              }}
            >
              {t('getCode')}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
