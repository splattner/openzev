import { describe, it, expect, vi } from 'vitest'
import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { act } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MantineProvider } from '@mantine/core'
import { InvoiceDetailPage } from '../src/pages/InvoiceDetailPage'

vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (k: string) => k, i18n: { language: 'en', changeLanguage: vi.fn() } }),
}))

const mockAuth = vi.fn()
vi.mock('../src/lib/auth', () => ({ useAuth: () => mockAuth() }))
vi.mock('../src/lib/appSettings', () => ({
    useAppSettings: () => ({ settings: {}, isLoading: false }),
    formatShortDate: (v: string | null | undefined) => v ?? '',
}))
// A participant has no live invoice (#862): the detail request is a 404.
vi.mock('../src/lib/api/invoices', () => ({
    fetchInvoice: vi.fn(() => Promise.reject(new Error('Not found'))),
    fetchInvoicePdfBlob: vi.fn(),
    generateInvoicePdf: vi.fn(),
}))

async function renderAt(path: string) {
    const container = document.createElement('div')
    document.body.appendChild(container)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const root = createRoot(container)
    await act(async () => {
        root.render(createElement(MemoryRouter, { initialEntries: [path] },
            createElement(QueryClientProvider, { client }, createElement(MantineProvider, null,
                createElement(Routes, null,
                    createElement(Route, { path: '/billing/invoices/:invoiceId', element: createElement(InvoiceDetailPage) }),
                    createElement(Route, { path: '/me/documents', element: createElement('p', null, 'MY DOCUMENTS') }),
                ),
            )),
        ))
    })
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 50)) })
    return container
}

function account(access: 'manager' | null, role: 'user' | 'admin' = 'user') {
    mockAuth.mockReturnValue({
        user: {
            id: 7, username: 'x@example.com', role,
            memberships: [{ zev: 'z1', zev_name: 'Z', zev_disabled: false, access, participants: [{ id: 'p1', valid_from: '2026-01-01', valid_to: null, live: true }] }],
        },
    })
}

describe('an invoice link a participant can no longer open', () => {
    it('lands on My documents instead of an error that a retry cannot fix', async () => {
        account(null)
        const container = await renderAt('/billing/invoices/42')
        expect(container.textContent).toContain('MY DOCUMENTS')
        expect(container.textContent).not.toContain('common.error')
        container.remove()
    })

    it.each([['manager' as const, 'user' as const], [null, 'admin' as const]])('keeps the error and retry for an account that manages (%s, %s)', async (access, role) => {
        account(access, role)
        const container = await renderAt('/billing/invoices/42')
        expect(container.textContent).not.toContain('MY DOCUMENTS')
        expect(container.textContent).toContain('common.error')
        container.remove()
    })
})
