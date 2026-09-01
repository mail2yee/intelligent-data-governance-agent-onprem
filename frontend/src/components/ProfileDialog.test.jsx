import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { makeT } from '../i18n'
import * as api from '../api'
import ProfileDialog from './ProfileDialog'

vi.mock('../api')

describe('ProfileDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders nothing when closed', () => {
    const { container } = render(
      <ProfileDialog t={makeT('en')} open={false} userKey="" onSave={() => {}} onClose={() => {}} />
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('shows the empty-preferences message when no userKey is set', () => {
    render(<ProfileDialog t={makeT('en')} open={true} userKey="" onSave={() => {}} onClose={() => {}} />)
    expect(api.getPreferences).not.toHaveBeenCalled()
    expect(screen.getByText(/Nothing remembered yet/)).toBeInTheDocument()
  })

  it('fetches and renders remembered preferences for a set userKey', async () => {
    api.getPreferences.mockResolvedValue({ preferences: ['usually asks about capacity data'] })
    render(
      <ProfileDialog
        t={makeT('en')}
        open={true}
        userKey="tim@example.com"
        onSave={() => {}}
        onClose={() => {}}
      />
    )
    await waitFor(() => expect(api.getPreferences).toHaveBeenCalledWith('tim@example.com'))
    expect(await screen.findByText('usually asks about capacity data')).toBeInTheDocument()
  })

  it('calls onSave with the trimmed name when saved', async () => {
    api.getPreferences.mockResolvedValue({ preferences: [] })
    const onSave = vi.fn()
    render(<ProfileDialog t={makeT('en')} open={true} userKey="" onSave={onSave} onClose={() => {}} />)

    await userEvent.type(screen.getByPlaceholderText(/e.g. Tim/), '  tim@example.com  ')
    await userEvent.click(screen.getByText('Save'))

    expect(onSave).toHaveBeenCalledWith('tim@example.com')
  })

  it('clears preferences and updates the list when clear is clicked', async () => {
    api.getPreferences.mockResolvedValue({ preferences: ['usually asks about capacity data'] })
    api.clearPreferences.mockResolvedValue({ status: 'success' })
    render(
      <ProfileDialog
        t={makeT('en')}
        open={true}
        userKey="tim@example.com"
        onSave={() => {}}
        onClose={() => {}}
      />
    )

    await screen.findByText('usually asks about capacity data')
    await userEvent.click(screen.getByText('Clear remembered preferences'))

    expect(api.clearPreferences).toHaveBeenCalledWith('tim@example.com')
    await waitFor(() => expect(screen.queryByText('usually asks about capacity data')).not.toBeInTheDocument())
    expect(screen.getByText(/Nothing remembered yet/)).toBeInTheDocument()
  })

  it('calls onClose when close is clicked', async () => {
    api.getPreferences.mockResolvedValue({ preferences: [] })
    const onClose = vi.fn()
    render(<ProfileDialog t={makeT('en')} open={true} userKey="" onSave={() => {}} onClose={onClose} />)
    await userEvent.click(screen.getByText('Close'))
    expect(onClose).toHaveBeenCalled()
  })
})
