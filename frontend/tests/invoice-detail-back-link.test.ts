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

async function renderDetail(initialEntries: unknown[] = ['/billing/invoices/1']) {
    const container = document.createElement('div')
    document.body.appendChild(container)
    const client = new QueryClient()
    const root = createRoot(container)
    await act(async () => {
        root.render(
            createElement(
                MemoryRouter,
                { initialEntries: initialEntries as string[] },
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
    it('sends participants back to their own invoices list', async () => {
        mockRole('participant')
        const container = await renderDetail()
        const link = container.querySelector('header a.button') as HTMLAnchorElement
        expect(link.getAttribute('href')).toBe('/me/invoices')
        expect(link.textContent).toBe('common.back')
        container.remove()
    })

    it('honours a participant origin of My invoices or the statement page', async () => {
        mockRole('participant')
        for (const from of ['/me/invoices', '/me/statement', '/']) {
            const container = await renderDetail([{ pathname: '/billing/invoices/1', state: { from } }])
            const link = container.querySelector('header a.button') as HTMLAnchorElement
            expect(link.getAttribute('href')).toBe(from)
            container.remove()
        }
    })

    it('keeps the invoices return for owners', async () => {
        mockRole('zev_owner')
        const container = await renderDetail()
        const link = container.querySelector('header a.button') as HTMLAnchorElement
        expect(link.getAttribute('href')).toBe('/billing/invoices')
        expect(link.textContent).toBe('pages.invoiceDetail.backToInvoices')
        container.remove()
    })

    it('returns owners to the dashboard origin', async () => {
        mockRole('zev_owner')
        const container = await renderDetail([{ pathname: '/billing/invoices/1', state: { from: '/' } }])
        const link = container.querySelector('header a.button') as HTMLAnchorElement
        expect(link.getAttribute('href')).toBe('/')
        container.remove()
    })

    it('returns owners to the invoice period they came from', async () => {
        mockRole('zev_owner')
        const container = await renderDetail([{
            pathname: '/billing/invoices/1',
            state: { from: '/billing/invoices', period_start: '2026-08-01', period_end: '2026-08-31' },
        }])
        const link = container.querySelector('header a.button') as HTMLAnchorElement
        expect(link.getAttribute('href')).toBe('/billing/invoices?period_start=2026-08-01&period_end=2026-08-31')
        container.remove()
    })

    it('returns owners to a historical period that no longer aligns', async () => {
        mockRole('zev_owner')
        const container = await renderDetail([{
            pathname: '/billing/invoices/1',
            state: { from: '/billing/invoices', period_start: '2026-02-01', period_end: '2026-02-28' },
        }])
        const link = container.querySelector('header a.button') as HTMLAnchorElement
        expect(link.getAttribute('href')).toBe('/billing/invoices?period_start=2026-02-01&period_end=2026-02-28')
        container.remove()
    })

    it('hides the generate-PDF control from participants', async () => {
        mockRole('participant')
        const container = await renderDetail()
        // Document-unavailable state renders, but no owner-only action.
        expect(container.textContent).toContain('pdf.noDocument')
        const buttons = Array.from(container.querySelectorAll('button'))
        expect(buttons.some((b) => b.textContent === 'pages.invoiceDetail.generatePdf')).toBe(false)
        container.remove()
    })

    it('keeps the generate-PDF control for owners', async () => {
        mockRole('zev_owner')
        const container = await renderDetail()
        const buttons = Array.from(container.querySelectorAll('button'))
        expect(buttons.some((b) => b.textContent === 'pages.invoiceDetail.generatePdf')).toBe(true)
        container.remove()
    })
})
