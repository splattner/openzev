import { MantineProvider } from '@mantine/core'
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('../src/lib/auth', () => ({ useAuth: () => ({ user: { role: 'user' } }) }))
vi.mock('../src/lib/managedZev', () => {
    const context = {
        useManagedZev: () => ({ selectedZev: { id: 'z1', name: 'ZEV' }, relation: 'manager' }),
    }
    return { ...context, useOptionalManagedZev: context.useManagedZev }
})
vi.mock('../src/pages/InvoicesPage', () => ({ InvoicesContent: () => createElement('div') }))
vi.mock('../src/pages/BillingEmailsPage', () => ({ BillingEmailsPage: () => createElement('div') }))
vi.mock('../src/features/inbox/OutboxTab', () => ({ OutboxTab: () => createElement('div') }))

import { BillingHubPage } from '../src/pages/BillingHubPage'

const cleanups: Array<() => void> = []
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))

describe('billing hub information architecture', () => {
    beforeAll(() => {
        const style = document.createElement('style')
        style.textContent = readFileSync(resolve(__dirname, '../src/styles/components/app-tabs.css'), 'utf8')
        document.head.appendChild(style)
    })

    function mountHub(tab: 'invoices' | 'emails' | 'documents') {
        const container = document.createElement('div')
        document.body.appendChild(container)
        const root = createRoot(container)
        act(() => root.render(createElement(
            MemoryRouter,
            null,
            createElement(MantineProvider, null, createElement(BillingHubPage, { tab })),
        )))
        cleanups.push(() => {
            act(() => root.unmount())
            container.remove()
        })
        return container
    }

    it('puts invoices first and has no duplicate periods tab', () => {
        const container = mountHub('invoices')

        const tabs = [...container.querySelectorAll('[role="tab"]')].map((tab) => tab.textContent)
        expect(tabs).toEqual([
            'pages.billingHub.tabs.invoices',
            'pages.billingHub.tabs.emails',
            'pages.billingHub.tabs.documents',
        ])
        expect(container.textContent).not.toContain('pages.billingHub.tabs.periods')
    })

    it.each(['invoices', 'emails', 'documents'] as const)('spaces the active %s panel', (tab) => {
        const container = mountHub(tab)

        const activeTab = container.querySelector('[role="tab"][aria-selected="true"]')!
        const panel = document.getElementById(activeTab.getAttribute('aria-controls')!)!
        expect(getComputedStyle(panel).display).toBe('grid')
        expect(getComputedStyle(panel).gap).toBe('1rem')
    })
})
