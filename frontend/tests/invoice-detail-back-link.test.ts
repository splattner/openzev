import { describe, it, expect, vi } from 'vitest'
import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { act } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MantineProvider } from '@mantine/core'
import { InvoiceDetailPage } from '../src/pages/InvoiceDetailPage'
import type { UserRole } from '../src/types/api'

vi.mock('react-i18next', () => ({
    useTranslation: () => ({
        t: (k: string) => k,
        i18n: { language: 'en', changeLanguage: vi.fn() },
    }),
}))

const mockAuth = vi.fn()

vi.mock('../src/lib/auth', () => ({
    useAuth: () => mockAuth(),
}))

vi.mock('../src/lib/appSettings', () => ({
    useAppSettings: () => ({ settings: {}, isLoading: false }),
    formatShortDate: (v: string | null | undefined) => v ?? '',
}))

vi.mock('../src/lib/api/invoices', () => ({
    fetchInvoice: vi.fn(() =>
        Promise.resolve({
            id: '1',
            invoice_number: 'R-1',
            zev_name: 'Muster ZEV',
            participant_name: 'Anna Consumer',
            period_start: '2026-01-01',
            period_end: '2026-01-31',
            status: 'sent',
            total_chf: '10.00',
            pdf_url: null,
        }),
    ),
    fetchInvoicePdfBlob: vi.fn(),
    generateInvoicePdf: vi.fn(),
}))

function mockRole(role: UserRole) {
    mockAuth.mockReturnValue({ user: { id: 7, username: `${role}@x.ch`, role } })
}

async function renderDetail() {
    const container = document.createElement('div')
    document.body.appendChild(container)
    const client = new QueryClient()
    const root = createRoot(container)
    await act(async () => {
        root.render(
            createElement(
                MemoryRouter,
                { initialEntries: ['/billing/invoices/1'] },
                createElement(
                    QueryClientProvider,
                    { client },
                    createElement(
                        MantineProvider,
                        null,
                        createElement(Routes, null, createElement(Route, {
                            path: '/billing/invoices/:invoiceId',
                            element: createElement(InvoiceDetailPage),
                        })),
                    ),
                ),
            ),
        )
    })
    for (let i = 0; i < 100 && !container.querySelector('header a.button'); i += 1) {
        await act(async () => {
            await new Promise((r) => setTimeout(r, 50))
        })
    }
    return container
}

describe('InvoiceDetailPage return link', () => {
    it('sends participants to the dashboard, not the guarded invoices list', async () => {
        mockRole('participant')
        const container = await renderDetail()
        const link = container.querySelector('header a.button') as HTMLAnchorElement
        expect(link.getAttribute('href')).toBe('/')
        expect(link.textContent).toBe('common.back')
        container.remove()
    })

    it('keeps the invoices return for owners', async () => {
        mockRole('zev_owner')
        const container = await renderDetail()
        const link = container.querySelector('header a.button') as HTMLAnchorElement
        expect(link.getAttribute('href')).toBe('/billing/invoices')
        expect(link.textContent).toBe('pages.invoiceDetail.backToInvoices')
        container.remove()
    })
})
