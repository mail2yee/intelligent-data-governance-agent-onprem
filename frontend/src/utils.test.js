import { describe, expect, it, vi } from 'vitest'
import { approvalHours, initials } from './utils'

describe('initials', () => {
  it('takes the first letter of each underscore-separated part', () => {
    expect(initials('capacity_director@example.com')).toBe('CD')
    expect(initials('fab_ops_owner@example.com')).toBe('FO')
  })

  it('handles a single-word local part', () => {
    expect(initials('admin@example.com')).toBe('A')
  })
})

describe('approvalHours', () => {
  it('uses cycle_time_seconds when decided', () => {
    const hours = approvalHours({ decision: 'Approve', cycle_time_seconds: 7200 })
    expect(hours).toBe(2)
  })

  it('computes elapsed time from created_at when still pending', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-01-01T03:00:00Z'))
    const hours = approvalHours({ decision: 'PENDING', created_at: '2026-01-01T00:00:00Z' })
    expect(hours).toBeCloseTo(3, 5)
    vi.useRealTimers()
  })

  it('returns 0 for a pending approval with no created_at and no cycle time', () => {
    expect(approvalHours({ decision: 'PENDING' })).toBe(0)
  })
})
