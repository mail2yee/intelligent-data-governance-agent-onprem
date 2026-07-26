import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { makeT } from '../i18n'
import NavRail from './NavRail'

describe('NavRail', () => {
  it('marks the active view and shows the pending count badge', () => {
    render(<NavRail t={makeT('en')} view="discover" onChangeView={() => {}} pendingCount={3} />)
    expect(screen.getByText('Discover & Request').closest('button')).toHaveClass('active')
    expect(screen.getByText('Approvals & Tracking').closest('button')).not.toHaveClass('active')
    expect(screen.getByText('3')).toBeInTheDocument()
  })

  it('calls onChangeView with the clicked view', async () => {
    const onChangeView = vi.fn()
    render(<NavRail t={makeT('en')} view="discover" onChangeView={onChangeView} pendingCount={0} />)
    await userEvent.click(screen.getByText('Approvals & Tracking'))
    expect(onChangeView).toHaveBeenCalledWith('approvals')
  })

  it('collapses and re-expands a group when its label is clicked', async () => {
    render(<NavRail t={makeT('en')} view="discover" onChangeView={() => {}} pendingCount={0} />)
    const workspaceLabel = screen.getByText('Workspace')
    const discoverButton = screen.getByText('Discover & Request')

    expect(discoverButton).toBeVisible()

    await userEvent.click(workspaceLabel)
    expect(discoverButton.closest('.group-items')).toHaveClass('collapsed')

    await userEvent.click(workspaceLabel)
    expect(discoverButton.closest('.group-items')).not.toHaveClass('collapsed')
  })
})
