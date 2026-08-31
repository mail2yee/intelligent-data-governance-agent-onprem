import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { makeT } from '../i18n'
import DiscoverView from './DiscoverView'

// streamChat() itself is unit-tested in api.test.js - mocked here so
// these tests only exercise DiscoverView's own history-tracking state
// machine (see chat.py's run_chat() docstring for the backend half of
// this feature).
vi.mock('../api', () => ({ streamChat: vi.fn() }))
import { streamChat } from '../api'

const CATALOG = {
  'customer-capacity-allocation': {
    id: 'customer-capacity-allocation',
    name: 'Specific Customer Capacity Allocation',
    maturity_level: 'Gold',
    data_quality_score: '99%',
  },
}

// Drives a mocked streamChat call straight to its onFinal callback,
// mirroring what the real SSE stream eventually delivers.
function mockFinal({ reply, matched_products }) {
  streamChat.mockImplementation(async (_msg, _lang, _mode, _history, { onFinal }) => {
    onFinal({ reply, matched_products, thinking_steps: [] })
  })
}

describe('DiscoverView conversation history', () => {
  beforeEach(() => {
    streamChat.mockReset()
  })
  afterEach(() => {
    vi.clearAllMocks()
  })

  it('sends an empty history on the very first search', async () => {
    mockFinal({ reply: 'no match, please clarify', matched_products: [] })
    render(
      <DiscoverView t={makeT('en')} lang="en" catalog={CATALOG} cart={[]} onToggleCart={() => {}} />
    )

    await userEvent.type(screen.getByPlaceholderText(/e.g. I want to analyze/), 'vague request{Enter}')

    expect(streamChat).toHaveBeenCalledWith('vague request', 'en', 'keyword', [], expect.any(Object))
  })

  it('carries the prior exchange forward as history when a search stays unresolved', async () => {
    mockFinal({ reply: 'Which area is your report about?', matched_products: [] })
    render(
      <DiscoverView t={makeT('en')} lang="en" catalog={CATALOG} cart={[]} onToggleCart={() => {}} />
    )
    const input = screen.getByPlaceholderText(/e.g. I want to analyze/)

    await userEvent.type(input, 'I want a report{Enter}')
    await userEvent.clear(input)
    await userEvent.type(input, 'capacity{Enter}')

    expect(streamChat).toHaveBeenLastCalledWith(
      'capacity',
      'en',
      'keyword',
      [
        { role: 'user', content: 'I want a report' },
        { role: 'assistant', content: 'Which area is your report about?' },
      ],
      expect.any(Object)
    )
  })

  it('resets history once a search resolves to a real match', async () => {
    render(
      <DiscoverView t={makeT('en')} lang="en" catalog={CATALOG} cart={[]} onToggleCart={() => {}} />
    )
    const input = screen.getByPlaceholderText(/e.g. I want to analyze/)

    mockFinal({ reply: 'Which area is your report about?', matched_products: [] })
    await userEvent.type(input, 'I want a report{Enter}')

    mockFinal({ reply: 'Here you go.', matched_products: ['customer-capacity-allocation'] })
    await userEvent.clear(input)
    await userEvent.type(input, 'capacity{Enter}')

    // Resolved - a completely new, unrelated search afterward must not
    // drag the earlier (now-answered) exchange along.
    mockFinal({ reply: 'no match', matched_products: [] })
    await userEvent.clear(input)
    await userEvent.type(input, 'something new{Enter}')

    expect(streamChat).toHaveBeenLastCalledWith('something new', 'en', 'keyword', [], expect.any(Object))
  })

  it('resets history when a chip starts a fresh example search', async () => {
    render(
      <DiscoverView t={makeT('en')} lang="en" catalog={CATALOG} cart={[]} onToggleCart={() => {}} />
    )
    const input = screen.getByPlaceholderText(/e.g. I want to analyze/)

    mockFinal({ reply: 'Which area is your report about?', matched_products: [] })
    await userEvent.type(input, 'I want a report{Enter}')

    mockFinal({ reply: 'chip reply', matched_products: [] })
    await userEvent.click(screen.getAllByRole('button', { name: /.+/ }).find((b) => b.className === 'chip'))

    expect(streamChat).toHaveBeenLastCalledWith(expect.any(String), 'en', 'keyword', [], expect.any(Object))
  })
})
