import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { makeT } from '../i18n'
import TopBar from './TopBar'

describe('TopBar', () => {
  it('shows "?" when no userKey is set', () => {
    render(<TopBar t={makeT('en')} userKey="" onToggleLang={() => {}} onToggleTheme={() => {}} onOpenProfile={() => {}} />)
    expect(screen.getByText('?')).toBeInTheDocument()
  })

  it('shows initials derived from an email userKey', () => {
    render(
      <TopBar
        t={makeT('en')}
        userKey="tim@example.com"
        onToggleLang={() => {}}
        onToggleTheme={() => {}}
        onOpenProfile={() => {}}
      />
    )
    expect(screen.getByText('T')).toBeInTheDocument()
  })

  it('shows initials derived from a two-word name', () => {
    render(
      <TopBar
        t={makeT('en')}
        userKey="Tim Shen"
        onToggleLang={() => {}}
        onToggleTheme={() => {}}
        onOpenProfile={() => {}}
      />
    )
    expect(screen.getByText('TS')).toBeInTheDocument()
  })

  it('calls onOpenProfile when the avatar is clicked', async () => {
    const onOpenProfile = vi.fn()
    render(
      <TopBar t={makeT('en')} userKey="" onToggleLang={() => {}} onToggleTheme={() => {}} onOpenProfile={onOpenProfile} />
    )
    await userEvent.click(screen.getByText('?'))
    expect(onOpenProfile).toHaveBeenCalled()
  })
})
