import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { makeT } from '../i18n'
import TicketRow from './TicketRow'

const BASE_TICKET = {
  id: 'FAB-ABC123',
  products: ['customer-capacity-allocation'],
  purpose: 'PoC',
  objective: 'Assess Q3 capacity',
  status: 'PENDING_APPROVAL',
  owners: ['a@example.com', 'b@example.com'],
  approvals: {
    'a@example.com': { decision: 'Approve', cycle_time_seconds: 3600 },
    'b@example.com': { decision: 'PENDING', created_at: new Date().toISOString() },
  },
}

describe('TicketRow', () => {
  it('is collapsed by default and expands on click', async () => {
    render(<TicketRow ticket={BASE_TICKET} t={makeT('en')} onApprove={() => {}} onShowCode={() => {}} />)
    expect(screen.getByText(/FAB-ABC123/).closest('.ticket-row')).not.toHaveClass('open')
    await userEvent.click(screen.getByText(/FAB-ABC123/))
    expect(screen.getByText(/FAB-ABC123/).closest('.ticket-row')).toHaveClass('open')
  })

  it('calls onApprove with Approve when the approve button is clicked', async () => {
    const onApprove = vi.fn()
    render(<TicketRow ticket={BASE_TICKET} t={makeT('en')} onApprove={onApprove} onShowCode={() => {}} />)
    await userEvent.click(screen.getByText('Approve'))
    expect(onApprove).toHaveBeenCalledWith('FAB-ABC123', 'b@example.com', 'Approve', '')
  })

  describe('reject flow', () => {
    let promptSpy
    let alertSpy
    beforeEach(() => {
      promptSpy = vi.spyOn(window, 'prompt')
      alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {})
    })
    afterEach(() => {
      promptSpy.mockRestore()
      alertSpy.mockRestore()
    })

    it('calls onApprove with Reject and the entered reason', async () => {
      promptSpy.mockReturnValue('not needed right now')
      const onApprove = vi.fn()
      render(<TicketRow ticket={BASE_TICKET} t={makeT('en')} onApprove={onApprove} onShowCode={() => {}} />)
      await userEvent.click(screen.getByText('Reject'))
      expect(onApprove).toHaveBeenCalledWith('FAB-ABC123', 'b@example.com', 'Reject', 'not needed right now')
    })

    it('does not call onApprove if no reason is entered', async () => {
      promptSpy.mockReturnValue('')
      const onApprove = vi.fn()
      render(<TicketRow ticket={BASE_TICKET} t={makeT('en')} onApprove={onApprove} onShowCode={() => {}} />)
      await userEvent.click(screen.getByText('Reject'))
      expect(onApprove).not.toHaveBeenCalled()
      expect(alertSpy).toHaveBeenCalled()
    })
  })

  it('shows an SLA warning banner when a pending approver has waited over 24 hours', () => {
    const staleTicket = {
      ...BASE_TICKET,
      approvals: {
        ...BASE_TICKET.approvals,
        'b@example.com': {
          decision: 'PENDING',
          created_at: new Date(Date.now() - 30 * 3600 * 1000).toISOString(),
        },
      },
    }
    render(<TicketRow ticket={staleTicket} t={makeT('en')} onApprove={() => {}} onShowCode={() => {}} />)
    expect(screen.getByText(/SLA warning/)).toBeInTheDocument()
  })

  it('does not show an SLA banner when everyone is well within 24 hours', () => {
    render(<TicketRow ticket={BASE_TICKET} t={makeT('en')} onApprove={() => {}} onShowCode={() => {}} />)
    expect(screen.queryByText(/SLA warning/)).not.toBeInTheDocument()
  })

  it('shows a "get connection code" link only when the ticket is approved', () => {
    const { rerender } = render(
      <TicketRow ticket={BASE_TICKET} t={makeT('en')} onApprove={() => {}} onShowCode={() => {}} />
    )
    expect(screen.queryByText(/Get connection code/)).not.toBeInTheDocument()

    rerender(
      <TicketRow ticket={{ ...BASE_TICKET, status: 'APPROVED' }} t={makeT('en')} onApprove={() => {}} onShowCode={() => {}} />
    )
    expect(screen.getByText(/Get connection code/)).toBeInTheDocument()
  })

  it('calls onShowCode with the ticket\'s first product when the code link is clicked', async () => {
    const onShowCode = vi.fn()
    render(
      <TicketRow
        ticket={{ ...BASE_TICKET, status: 'APPROVED' }}
        t={makeT('en')}
        onApprove={() => {}}
        onShowCode={onShowCode}
      />
    )
    await userEvent.click(screen.getByText(/Get connection code/))
    expect(onShowCode).toHaveBeenCalledWith('customer-capacity-allocation')
  })
})
