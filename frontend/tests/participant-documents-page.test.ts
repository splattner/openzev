import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import { MantineProvider } from '@mantine/core'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('../src/lib/auth', () => ({ useAuth: () => ({ user: { role: 'user' } }) }))
vi.mock('../src/lib/managedZev', () => {
    const context = { useManagedZev: () => ({ selectedZev: { id: 'z1', name: 'Sonnenhof' }, relation: 'manager' }) }
    return { ...context, useOptionalManagedZev: context.useManagedZev }
})
vi.mock('../src/features/inbox/Outbox', () => ({ Outbox: () => createElement('div', { 'data-testid': 'outbox' }) }))

import { ParticipantDocumentsPage } from '../src/pages/ParticipantDocumentsPage'

const cleanups: Array<() => void> = []
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))

describe('ParticipantDocumentsPage', () => {
    it('is a page of its own: the community, a title and the outbox, with no billing tabs', () => {
        const container = document.createElement('div')
        document.body.appendChild(container)
        const root = createRoot(container)
        act(() => root.render(createElement(MemoryRouter, null, createElement(MantineProvider, null, createElement(ParticipantDocumentsPage)))))
        cleanups.push(() => { act(() => root.unmount()); container.remove() })

        expect(container.querySelector('h1')?.textContent).toBe('nav.participantDocuments')
        expect(container.textContent).toContain('pages.participantDocuments.description')
        expect(container.textContent).toContain('Sonnenhof')
        expect(container.querySelector('[data-testid="outbox"]')).not.toBeNull()
        expect(container.querySelector('[role="tablist"]')).toBeNull()
    })
})
