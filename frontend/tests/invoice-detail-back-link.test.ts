import { describe, it, expect, vi } from 'vitest'
import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { act } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MantineProvider } from '@mantine/core'
import { fetchInvoice } from '../src/lib/api/invoices'
import { InvoiceDetailPage } from '../src/pages/InvoiceDetailPage'
import { ToastProvider } from '../src/lib/toast'

vi.mock('react-i18next', () => ({
    useTranslation: () => ({
        t: (k: string, values?: Record<string, unknown>) => values ? `${k} ${JSON.stringify(values)}` : k,
        i18n: { language: 'en', changeLanguage: vi.fn() },
    }),
}))

const mockAuth = vi.fn()
vi.mock('../src/lib/managedZev', () => ({ useManagedZev: () => ({ setSelectedZevId: vi.fn() }), useOptionalManagedZev: () => null }))

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
            zev: 'z1',
            zev_name: 'Muster ZEV',
            participant_name: 'Anna Consumer',
            period_start: '2026-01-01',
            period_end: '2026-01-31',
            status: 'sent',
            total_chf: '10.00',
            pdf_url: null,
        }),
    ),
    fetchInvoicePdfBlob: vi.fn(async () => { throw new Error('PDF unavailable') }),
    generateInvoicePdf: vi.fn(),
    previewInvoiceCalculation: vi.fn(async () => ({ total_chf: '10.00', total_local_kwh: '0.0000', total_grid_kwh: '0.0000', total_feed_in_kwh: '0.0000' })),
}))

/** A non-admin account managing, or taking part in, the invoice's community (#761). */
function mockRole(relation: 'manager' | 'participant', disabled = false) {
    const membership = {
        zev: 'z1', zev_name: 'Muster ZEV', zev_disabled: disabled,
        access: relation === 'manager' ? 'manager' : null,
        participants: relation === 'participant' ? [{ id: 'p1', valid_from: '2026-01-01', valid_to: null, live: true }] : [],
    }
    mockAuth.mockReturnValue({ user: { id: 7, username: `${relation}@x.ch`, role: 'user', memberships: [membership] } })
}

async function renderDetail(initialEntries: unknown[] = ['/billing/invoices/1']) {
    const container = document.createElement('div')
    document.body.appendChild(container)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
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
                            element: createElement(ToastProvider, null, createElement(InvoiceDetailPage)),
                        })),
                    ),
                ),
            ),
        )
    })
    for (let i = 0; i < 100 && !container.querySelector('header a.button, [role="alert"]'); i += 1) {
        await act(async () => {
            await new Promise((r) => setTimeout(r, 50))
        })
    }
    return container
}

describe('InvoiceDetailPage return link', () => {
    it.each([false, true])('uses the invoice community write state for correction wording (disabled=%s)', async disabled => {
        mockRole('manager', disabled)
        const inv = await fetchInvoice('1')
        vi.mocked(fetchInvoice).mockResolvedValueOnce({ ...inv, needs_data_review: true, open_data_impact_count: 1 })
        const container = await renderDetail()
        expect(container.textContent).toContain(disabled
            ? 'pages.invoices.dataReview.issuedNotice'
            : 'pages.invoices.dataReview.issuedAction')
        container.remove()
    })

    it.each([
        ['draft', true, '/stored.pdf', 'pdfPendingChanges'],
        ['approved', true, '/stored.pdf', 'pdfIssuedOriginal'],
        ['sent', true, '/stored.pdf', 'pdfIssuedOriginal'],
        ['draft', false, '/stored.pdf', null],
        ['draft', true, null, null],
    ] as const)('labels the stored PDF for %s (review=%s, PDF=%s)', async (status, needsReview, pdfUrl, label) => {
        mockRole('manager')
        const inv = await fetchInvoice('1')
        vi.mocked(fetchInvoice).mockResolvedValueOnce({ ...inv, status, needs_data_review: needsReview, pdf_url: pdfUrl })
        const container = await renderDetail()
        const pdf = container.querySelector('section[aria-label="pdf.previewTitle"]')!
        expect(pdf).toBeTruthy()
        expect(pdf.textContent).not.toContain(label === 'pdfPendingChanges' ? 'pdfIssuedOriginal' : 'pdfPendingChanges')
        if (label) expect(pdf.textContent).toContain(`pages.invoices.dataReview.${label}`)
        else expect(pdf.textContent).not.toContain('pdfIssuedOriginal')
        container.remove()
    })

    it('gives an unavailable invoice a working return link without a pointless retry', async () => {
        mockRole('participant')
        vi.mocked(fetchInvoice).mockRejectedValueOnce({ response: { status: 404 } })
        const container = await renderDetail()
        expect(container.textContent).toContain('pages.invoices.dataReview.unavailable')
        expect(container.querySelector('button')).toBeNull()
        expect(container.querySelector('a.button')?.getAttribute('href')).toBe('/')
        container.remove()
    })

    it('sends participants back to their documents', async () => {
        mockRole('participant')
        const container = await renderDetail()
        const link = container.querySelector('header a.button') as HTMLAnchorElement
        expect(link.getAttribute('href')).toBe('/me/documents')
        expect(link.textContent).toBe('common.back')
        container.remove()
    })

    it('honours a participant origin of My documents or the statement page', async () => {
        mockRole('participant')
        for (const from of ['/me/documents', '/me/statement', '/']) {
            const container = await renderDetail([{ pathname: '/billing/invoices/1', state: { from } }])
            const link = container.querySelector('header a.button') as HTMLAnchorElement
            expect(link.getAttribute('href')).toBe(from)
            container.remove()
        }
    })

    it('keeps the invoices return for owners', async () => {
        mockRole('manager')
        const container = await renderDetail()
        const link = container.querySelector('header a.button') as HTMLAnchorElement
        expect(link.getAttribute('href')).toBe('/billing/invoices')
        expect(link.textContent).toBe('pages.invoiceDetail.backToInvoices')
        container.remove()
    })

    it('returns owners to the dashboard origin', async () => {
        mockRole('manager')
        const container = await renderDetail([{ pathname: '/billing/invoices/1', state: { from: '/' } }])
        const link = container.querySelector('header a.button') as HTMLAnchorElement
        expect(link.getAttribute('href')).toBe('/')
        container.remove()
    })

    it('returns platform administrators to their invoice list origin', async () => {
        mockAuth.mockReturnValue({ user: { id: 1, role: 'admin' } })
        const container = await renderDetail([{ pathname: '/billing/invoices/1', state: { from: '/admin/invoices' } }])
        expect(container.querySelector('header a.button')?.getAttribute('href')).toBe('/admin/invoices')
        container.remove()
    })

    it('returns owners to the invoice period they came from', async () => {
        mockRole('manager')
        const container = await renderDetail([{
            pathname: '/billing/invoices/1',
            state: { from: '/billing/invoices', period_start: '2026-08-01', period_end: '2026-08-31' },
        }])
        const link = container.querySelector('header a.button') as HTMLAnchorElement
        expect(link.getAttribute('href')).toBe('/billing/invoices?period_start=2026-08-01&period_end=2026-08-31')
        container.remove()
    })

    it('returns owners to a historical period that no longer aligns', async () => {
        mockRole('manager')
        const container = await renderDetail([{
            pathname: '/billing/invoices/1',
            state: { from: '/billing/invoices', period_start: '2026-02-01', period_end: '2026-02-28' },
        }])
        const link = container.querySelector('header a.button') as HTMLAnchorElement
        expect(link.getAttribute('href')).toBe('/billing/invoices?period_start=2026-02-01&period_end=2026-02-28')
        container.remove()
    })

    it.each([['9.00', 'recalculatedChanged'], ['10.00', 'recalculatedUnchanged']])('shows the recalculation result for a previous total of %s', async (before, message) => {
        mockRole('manager')
        vi.mocked(fetchInvoice).mockResolvedValueOnce({
            id: '1', invoice_number: 'NEW', zev: 'z1', zev_name: 'Muster ZEV', participant: 'p1', participant_name: 'Anna',
            period_start: '2026-01-01', period_end: '2026-01-31', status: 'draft', total_chf: '10.00',
            total_grid_kwh: '4.0001', total_local_kwh: '1.0000', pdf_url: null,
        })
        const container = await renderDetail([{ pathname: '/billing/invoices/1', state: {
            recalculation: { invoiceId: '1', before: { invoice_number: 'OLD', total_chf: before, total_grid_kwh: '4.0000', total_local_kwh: '1.0000' } },
        } }])
        const result = container.querySelector('.page-stack > div[role="status"]')!
        expect(container.querySelector('.success-banner')).toBeNull()
        expect(result.textContent).toContain(`pages.invoices.dataReview.${message}`)
        expect(result.textContent).toContain('CHF 10.00')
        expect(result.textContent).toContain('OLD')
        expect(result.textContent).toContain('4.0001')
        expect(result.textContent).not.toContain('pages.invoiceDetail.local')
        container.remove()
    })

    it('does not show an old recalculation result on another invoice', async () => {
        mockRole('manager')
        const container = await renderDetail([{ pathname: '/billing/invoices/1', state: {
            recalculation: { invoiceId: 'another-invoice', before: { invoice_number: 'OLD', total_chf: '9.00' } },
        } }])
        expect(container.textContent).not.toContain('pages.invoices.dataReview.recalculated')
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
        mockRole('manager')
        const container = await renderDetail()
        const buttons = Array.from(container.querySelectorAll('button'))
        expect(buttons.some((b) => b.textContent === 'pages.invoiceDetail.generatePdf')).toBe(true)
        container.remove()
    })
})
