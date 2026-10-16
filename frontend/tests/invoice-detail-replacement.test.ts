import { describe, it, expect, vi } from 'vitest'
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MantineProvider } from '@mantine/core'
import type { Invoice } from '../src/types/api'
import { InvoiceDetailPage } from '../src/pages/InvoiceDetailPage'

vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (k: string) => k, i18n: { language: 'en', changeLanguage: vi.fn() } }),
}))

vi.mock('../src/lib/auth', () => ({
    useAuth: () => ({
        user: {
            id: 7, username: 'manager@x.ch', role: 'user',
            memberships: [{ zev: 'z1', zev_name: 'Muster ZEV', zev_disabled: false, access: 'manager', participants: [] }],
        },
    }),
}))

vi.mock('../src/lib/appSettings', () => ({
    useAppSettings: () => ({ settings: {}, isLoading: false }),
    formatShortDate: (v: string | null | undefined) => v ?? '',
}))

const fetchInvoice = vi.fn()
vi.mock('../src/lib/api/invoices', () => ({
    fetchInvoice: (...args: unknown[]) => fetchInvoice(...args),
    fetchInvoicePdfBlob: vi.fn(),
    generateInvoicePdf: vi.fn(),
}))

const base: Invoice = {
    id: '1', invoice_number: 'R-2', zev: 'z1', zev_name: 'Muster ZEV', participant: 'p1', participant_name: 'Anna Consumer',
    period_start: '2026-01-01', period_end: '2026-01-31', status: 'draft', total_chf: '10.00', pdf_url: null,
}

async function renderDetail(invoice: Invoice) {
    fetchInvoice.mockResolvedValue(invoice)
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)
    await act(async () => {
        root.render(createElement(MemoryRouter, { initialEntries: ['/billing/invoices/1'] },
            createElement(QueryClientProvider, { client: new QueryClient() },
                createElement(MantineProvider, null,
                    createElement(Routes, null, createElement(Route, {
                        path: '/billing/invoices/:invoiceId', element: createElement(InvoiceDetailPage),
                    }))))))
    })
    for (let i = 0; i < 100 && !container.querySelector('.invoice-detail-meta'); i += 1) {
        await act(async () => { await new Promise((r) => setTimeout(r, 50)) })
    }
    const meta = container.querySelector('.invoice-detail-meta') as HTMLElement
    const links = [...meta.querySelectorAll('a')].map((a) => [a.textContent, a.getAttribute('href')])
    act(() => root.unmount())
    container.remove()
    return { text: meta.textContent ?? '', links }
}

describe('InvoiceDetailPage replacement links', () => {
    it('links a new invoice to the cancelled ones it replaces', async () => {
        const { text, links } = await renderDetail({
            ...base, replaces: [{ id: 'a', invoice_number: 'R-1' }, { id: 'b', invoice_number: 'R-0' }], replaced_by: null,
        })
        expect(text).toContain('pages.invoiceDetail.replaces R-1, R-0')
        expect(links).toEqual([['R-1', '/billing/invoices/a'], ['R-0', '/billing/invoices/b']])
    })

    it('links a cancelled invoice to the one that replaced it', async () => {
        const { text, links } = await renderDetail({
            ...base, status: 'cancelled', replaces: [], replaced_by: { id: 'c', invoice_number: 'R-3' },
        })
        expect(text).toContain('pages.invoiceDetail.replacedBy R-3')
        expect(links).toEqual([['R-3', '/billing/invoices/c']])
    })

    it('shows neither when the invoice stands alone', async () => {
        const { text } = await renderDetail({ ...base, replaces: [], replaced_by: null })
        expect(text).not.toContain('pages.invoiceDetail.replace')
    })
})
