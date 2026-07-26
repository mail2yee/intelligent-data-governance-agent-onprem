export function initials(email) {
  return email
    .split('@')[0]
    .split('_')
    .map((s) => s[0])
    .join('')
    .slice(0, 2)
    .toUpperCase()
}

// Hours elapsed for an approval: if still pending, time since it was
// created; if decided, the recorded cycle time.
export function approvalHours(a) {
  if (!a.cycle_time_seconds && a.decision === 'PENDING' && a.created_at) {
    return (Date.now() - new Date(a.created_at).getTime()) / 3600000
  }
  return (a.cycle_time_seconds || 0) / 3600
}
