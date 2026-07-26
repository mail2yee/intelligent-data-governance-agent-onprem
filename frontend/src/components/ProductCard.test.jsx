import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { makeT } from '../i18n'
import ProductCard from './ProductCard'

const PRODUCT = {
  id: 'customer-capacity-allocation',
  name: 'Specific Customer Capacity Allocation',
  description: 'Allocated capacity for a specific VIP customer.',
  maturity_level: 'Gold',
  data_quality_score: '99%',
  frequency: 'DAILY',
  tables_joined: 'capacity_plan, customer_commitment',
  owner: 'capacity_director@example.com',
}

describe('ProductCard', () => {
  it('renders the product fields', () => {
    render(<ProductCard product={PRODUCT} inCart={false} onToggleCart={() => {}} t={makeT('en')} />)
    expect(screen.getByText('Specific Customer Capacity Allocation')).toBeInTheDocument()
    expect(screen.getByText('customer-capacity-allocation')).toBeInTheDocument()
    expect(screen.getByText('Gold')).toBeInTheDocument()
    expect(screen.getByText('99%')).toBeInTheDocument()
  })

  it('shows "Add to request" when not in cart, and calls onToggleCart with the product id', async () => {
    const onToggleCart = vi.fn()
    render(<ProductCard product={PRODUCT} inCart={false} onToggleCart={onToggleCart} t={makeT('en')} />)

    const button = screen.getByRole('button')
    expect(button).toHaveTextContent('Add to request')

    await userEvent.click(button)
    expect(onToggleCart).toHaveBeenCalledWith('customer-capacity-allocation')
  })

  it('shows "Added" state when already in cart', () => {
    render(<ProductCard product={PRODUCT} inCart={true} onToggleCart={() => {}} t={makeT('en')} />)
    expect(screen.getByRole('button')).toHaveTextContent('Added')
  })

  it('uses the silver chip style for a Silver-maturity product', () => {
    render(
      <ProductCard product={{ ...PRODUCT, maturity_level: 'Silver' }} inCart={false} onToggleCart={() => {}} t={makeT('en')} />
    )
    expect(screen.getByText('Silver')).toHaveClass('silver')
  })
})
