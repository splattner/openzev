import { MantineProvider } from '@mantine/core'
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('../src/lib/managedZev', () => ({
    useManagedZev: () => ({ selectedZev: { id: 'z1', name: 'ZEV' } }),
}))
vi.mock('../src/pages/InvoicesPage', () => ({ InvoicesPage: () => createElement('div') }))
vi.mock('../src/pages/BillingEmailsPage', () => ({ BillingEmailsPage: () => createElement('div') }))
vi.mock('../src/pages/BillingStatementsPage', () => ({ BillingStatementsPage: () => createElement('div') }))

import { BillingHubPage } from '../src/pages/BillingHubPage'

const cleanups: Array<() => void> = []
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))

describe('billing hub information architecture', () => {
    it('puts invoices first and has no duplicate periods tab', () => {
        const container = document.createElement('div')
        document.body.appendChild(container)
        const root = createRoot(container)
        act(() => root.render(createElement(
            MemoryRouter,
            null,
            createElement(MantineProvider, null, createElement(BillingHubPage, { tab: 'invoices' })),
        )))
        cleanups.push(() => {
            act(() => root.unmount())
            container.remove()
        })

        const tabs = [...container.querySelectorAll('[role="tab"]')].map((tab) => tab.textContent)
        expect(tabs).toEqual([
            'pages.billingHub.tabs.invoices',
            'pages.billingHub.tabs.emails',
            'pages.billingHub.tabs.statements',
        ])
        expect(container.textContent).not.toContain('pages.billingHub.tabs.periods')
    })
})
