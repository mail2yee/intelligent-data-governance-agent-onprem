import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { makeT } from '../i18n'
import * as api from '../api'
import ConnectionCodeDialog from './ConnectionCodeDialog'

vi.mock('../api')

const META = { db_type: 'PostgreSQL', db_host: 'h', db_port: '5432', db_schema: 's' }

describe('ConnectionCodeDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.getConnectionMeta.mockResolvedValue(META)
  })

  it('renders nothing when no productId is set', () => {
    const { container } = render(
      <ConnectionCodeDialog t={makeT('en')} productId={null} onClose={() => {}} />
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('renders a result table when the query returns rows', async () => {
    api.queryProductData.mockResolvedValue({
      rows: [{ customer_name: 'Acme Semiconductor', utilization_pct: '95.83' }],
    })
    render(
      <ConnectionCodeDialog t={makeT('en')} productId="customer-capacity-allocation" onClose={() => {}} />
    )

    await userEvent.type(screen.getByPlaceholderText(/Describe what you want to look up/), 'which customers?')
    await userEvent.click(screen.getByText('Query'))

    await waitFor(() => expect(screen.getByText('Acme Semiconductor')).toBeInTheDocument())
    expect(api.queryProductData).toHaveBeenCalledWith('customer-capacity-allocation', 'which customers?')
    expect(screen.getByText('95.83')).toBeInTheDocument()
  })

  it('shows the empty-result message when nothing matches', async () => {
    api.queryProductData.mockResolvedValue({ rows: [] })
    render(
      <ConnectionCodeDialog t={makeT('en')} productId="customer-capacity-allocation" onClose={() => {}} />
    )

    await userEvent.type(screen.getByPlaceholderText(/Describe what you want to look up/), 'weather?')
    await userEvent.click(screen.getByText('Query'))

    await waitFor(() =>
      expect(screen.getByText('No matching data found for this question.')).toBeInTheDocument()
    )
  })

  it('shows a "not wired" message for a product without a real data source', async () => {
    api.queryProductData.mockRejectedValue(new Error('this product is not wired to a real data source'))
    render(<ConnectionCodeDialog t={makeT('en')} productId="move-forecast-summary" onClose={() => {}} />)

    await userEvent.type(screen.getByPlaceholderText(/Describe what you want to look up/), 'x')
    await userEvent.click(screen.getByText('Query'))

    await waitFor(() =>
      expect(
        screen.getByText('This data subject is not connected to a real database yet — connection code only.')
      ).toBeInTheDocument()
    )
  })

  it('does not query with a blank question', async () => {
    render(
      <ConnectionCodeDialog t={makeT('en')} productId="customer-capacity-allocation" onClose={() => {}} />
    )
    expect(screen.getByText('Query')).toBeDisabled()
    expect(api.queryProductData).not.toHaveBeenCalled()
  })

  it('resets query state when productId changes', async () => {
    api.queryProductData.mockResolvedValue({ rows: [{ customer_name: 'Acme Semiconductor' }] })
    const { rerender } = render(
      <ConnectionCodeDialog t={makeT('en')} productId="customer-capacity-allocation" onClose={() => {}} />
    )
    await userEvent.type(screen.getByPlaceholderText(/Describe what you want to look up/), 'which customers?')
    await userEvent.click(screen.getByText('Query'))
    await waitFor(() => expect(screen.getByText('Acme Semiconductor')).toBeInTheDocument())

    rerender(<ConnectionCodeDialog t={makeT('en')} productId="move-forecast-summary" onClose={() => {}} />)

    expect(screen.queryByText('Acme Semiconductor')).not.toBeInTheDocument()
    expect(screen.getByPlaceholderText(/Describe what you want to look up/).value).toBe('')
  })
})
