import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { MantineProvider } from '@mantine/core'
import type { Participant } from '../src/types/api'

import { ParticipantFormModal } from '../src/features/participants/ParticipantFormModal'

vi.mock('../src/lib/appSettings', () => ({
  useAppSettings: () => ({ settings: {}, isLoading: false }),
  toDayJsDateFormat: () => 'YYYY-MM-DD',
}))

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const participant: Participant = {
  id: 'p-1',
  zev: 'zev-1',
  user: 7,
  title: null,
  first_name: 'Anna',
  last_name: 'Consumer',
  email: 'anna@example.com',
  phone: null,
  address_line1: 'Musterstrasse 1',
  address_line2: null,
  postal_code: '8000',
  city: 'Zurich',
  notes: '',
  valid_from: '2026-01-01',
  valid_to: null,
  allocation_weight: '1.000',
  has_metering_point_assignment: true,
}

function renderModal(focusField: 'valid_to' | null) {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  act(() => {
    root.render(
      createElement(
        MantineProvider,
        null,
        createElement(ParticipantFormModal, {
          isOpen: true,
          title: 'title',
          onClose: () => undefined,
          onSubmit: () => undefined,
          initialParticipant: participant,
          selectedZevId: 'zev-1',
          isPending: false,
          focusField,
        }),
      ),
    )
  })
  return { container, root }
}

// The date picker's focusable trigger is a button; valid_from comes first, valid_to second.
function validToInput(container: HTMLElement): HTMLButtonElement | null {
  return container.querySelectorAll<HTMLButtonElement>('button[data-dates-input]')[1] ?? null
}

async function waitForFocus(input: HTMLElement) {
  for (let i = 0; i < 20 && document.activeElement !== input; i += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 25))
    })
  }
}

describe('ParticipantFormModal deep-link focus', () => {
  let container: HTMLElement
  let root: ReturnType<typeof createRoot>

  beforeEach(() => {
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      configurable: true,
      value: (query: string) => ({
        matches: false,
        media: query,
        onchange: null,
        addListener: () => undefined,
        removeListener: () => undefined,
        addEventListener: () => undefined,
        removeEventListener: () => undefined,
        dispatchEvent: () => false,
      }),
    })
  })

  afterEach(() => {
    act(() => root.unmount())
    container.remove()
  })

  it('focuses the validity field when opened from a ?focus&field=valid_to link', async () => {
    const rendered = renderModal('valid_to')
    container = rendered.container
    root = rendered.root
    const input = validToInput(container)
    expect(input).toBeTruthy()
    await waitForFocus(input)
    expect(document.activeElement).toBe(input)
  })

  it('leaves focus alone when no field is requested', async () => {
    const rendered = renderModal(null)
    container = rendered.container
    root = rendered.root
    const input = validToInput(container)
    expect(input).toBeTruthy()
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 120))
    })
    expect(document.activeElement).not.toBe(input)
  })
})
