import { act, createElement, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { MantineProvider } from '@mantine/core'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Invoice, InvoicePeriodParticipantRow } from '../src/types/api'

const api = vi.hoisted(() => ({ list: vi.fn(), open: vi.fn(), remove: vi.fn() }))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('../src/lib/api/invoices', () => ({ fetchInvoices: api.list, openInvoicePdf: api.open, deleteInvoice: api.remove }))
vi.mock('../src/lib/auth', () => ({ useAuth: () => ({ user: { role: 'user', memberships: [{ participants: [{ id: 'p1' }] }, { participants: [] }] } }) }))
vi.mock('../src/lib/toast', () => ({ useToast: () => ({ pushToast: vi.fn() }) }))
vi.mock('../src/lib/appSettings', () => ({ useAppSettings: () => ({ settings: {} }), formatShortDate: (date: string) => date }))

import { InvoicePdfCell } from '../src/components/InvoicePresentation'
import { InvoicePeriodRowsTable } from '../src/features/invoices/InvoicePeriodRowsTable'
import { MyInvoicesPage } from '../src/pages/MyInvoicesPage'
import { AdminInvoicesContent } from '../src/pages/AdminInvoicesPage'

const invoice: Invoice = {
    id: 'i1', invoice_number: 'INV-1', zev: 'z1', zev_name: 'Community A', participant: 'p1', participant_name: 'Anna',
    period_start: '2026-02-01', period_end: '2026-02-28', status: 'sent', total_chf: '-12.30', pdf_url: '/stored.pdf', pdf_status: 'ready',
}
const cleanups: Array<() => void> = []
afterEach(() => cleanups.splice(0).forEach(cleanup => cleanup()))
beforeEach(() => { vi.clearAllMocks(); api.list.mockResolvedValue([invoice]) })

async function mount(body: ReactNode) {
    const container = document.createElement('div')
    document.body.append(container)
    const root = createRoot(container)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    function Location() {
        const location = useLocation()
        return createElement('output', null, JSON.stringify(location.state))
    }
    await act(async () => root.render(createElement(MemoryRouter, null,
        createElement(QueryClientProvider, { client }, createElement(MantineProvider, null, body)),
        createElement(Location),
    )))
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)) })
    cleanups.push(() => { act(() => root.unmount()); client.clear(); container.remove() })
    return { container, client }
}

describe('shared invoice presentation', () => {
    it.each([
        ['pending', null, 'pages.invoices.pdfGenerating'],
        ['failed', null, 'pages.invoices.pdfFailed'],
        ['none', null, 'pages.invoices.pdfMissing'],
        ['ready', '/stored.pdf', 'pages.invoices.pdfReady'],
        ['failed', '/stored.pdf', 'pages.invoices.pdfReady'],
    ] as const)('preserves PDF state %s with stored file %s', async (status, url, label) => {
        const { container } = await mount(createElement(InvoicePdfCell, { invoice: { ...invoice, pdf_status: status, pdf_url: url } }))
        expect(container.textContent).toContain(label)
        const button = container.querySelector('button')
        expect(!!button).toBe(!!url)
        if (button) {
            await act(async () => button.click())
            expect(api.open).toHaveBeenCalledWith('i1')
        }
    })

    it('honours local rendering state even when a stored document exists', async () => {
        const { container } = await mount(createElement(InvoicePdfCell, { invoice, pending: true }))
        expect(container.querySelector('[role="status"]')?.textContent).toContain('pages.invoices.pdfGenerating')
        expect(container.querySelector('button')).toBeNull()
    })

    it('keeps participant rows without invoices and their metering/eligibility states', async () => {
        const base: InvoicePeriodParticipantRow = {
            participant_id: 'p1', participant_name: 'Anna', metering_data_complete: false,
            participant_kind: 'person', participant_name_addition: '', participant_valid_from: '2026-01-01',
            participant_valid_to: null, party_id: 'party-1', metering_point_labels: [],
            metering_points_total: 2, metering_points_with_data: 1, missing_meter_ids: ['CH-1'],
            missing_meter_details: [{ meter_id: 'CH-1', missing_days: 2 }],
            generation_eligibility: null, invoice: { ...invoice, last_email_status: 'failed', email_logs: [{ status: 'sent' } as never] },
        }
        const { container } = await mount(createElement(InvoicePeriodRowsTable, {
            rows: [base, { ...base, participant_id: 'p2', invoice: null },
                { ...base, participant_id: 'p3', invoice: null, generation_eligibility: { state: 'covered', invoice_id: 'old', invoice_number: 'OLD' } }],
            period: { period_start: invoice.period_start, period_end: invoice.period_end },
            getPrimaryRowAction: () => null, getRowMenuItems: () => [], getRowWork: () => ({}),
            repeatedPartyIds: new Set<string>(),
        }))
        expect(container.querySelectorAll('tbody tr')).toHaveLength(3)
        expect(container.textContent).toContain('pages.invoices.issues.metering')
        expect(container.textContent).toContain('pages.invoices.metering.missingDays')
        expect(container.textContent).toContain('pages.invoices.notCreated')
        expect(container.textContent).toContain('pages.invoices.covered.label')
        // The delivery annotation wins over an older log entry.
        expect(container.querySelector('tbody tr .invoice-row-issues')?.textContent).toContain('pages.invoices.issues.delivery')
        expect(container.querySelector<HTMLElement>('tbody tr [data-step="sent"]')?.dataset.state).toBe('issue')
        expect(container.textContent).toContain('CHF −12.30')
        const link = container.querySelector('tbody a') as HTMLAnchorElement
        await act(async () => link.click())
        expect(JSON.parse(container.querySelector('output')!.textContent!)).toEqual({
            from: '/billing/invoices', period_start: '2026-02-01', period_end: '2026-02-28',
        })
    })

    it('requires ownership and sent visibility, retaining later cancellations and ignoring hidden PDF work', async () => {
        api.list.mockResolvedValue([
            invoice,
            { ...invoice, id: 'paid', status: 'paid' },
            { ...invoice, id: 'cancelled', status: 'cancelled', sent_at: '2026-03-01T12:00:00Z' },
            { ...invoice, id: 'draft', status: 'draft', sent_at: null, pdf_status: 'pending' },
            { ...invoice, id: 'approved', status: 'approved', sent_at: null },
            { ...invoice, id: 'never-sent', status: 'cancelled', sent_at: null },
            { ...invoice, id: 'other', participant: 'p2', pdf_status: 'pending' },
        ])
        const { container, client } = await mount(createElement(MyInvoicesPage))
        expect(container.querySelectorAll('tbody tr')).toHaveLength(3)
        // The public query options retain the polling predicate used by the page.
        const query = client.getQueryCache().getAll()[0]
        const interval = (query.options as { refetchInterval?: unknown }).refetchInterval as unknown as (entry: typeof query) => number | false
        expect(interval(query)).toBe(false)
    })

    it('shows only the load error for an initial admin invoice failure', async () => {
        api.list.mockRejectedValue(new Error('Offline'))
        const { container } = await mount(createElement(AdminInvoicesContent))
        expect(container.textContent).toContain('adminInvoices.loadError')
        expect(container.textContent).not.toContain('adminInvoices.empty')
    })

    it('keeps own invoices read-only with community labels, PDF feedback, origin and cached rows', async () => {
        api.list.mockResolvedValue([invoice, { ...invoice, id: 'i2', invoice_number: 'INV-2', zev_name: 'Community B', pdf_url: null, pdf_status: 'failed' }])
        const { container, client } = await mount(createElement(MyInvoicesPage))
        expect(api.list).toHaveBeenCalledWith(undefined)
        expect(container.querySelectorAll('tbody tr')).toHaveLength(2)
        expect(container.textContent).toContain('Community A')
        expect(container.textContent).toContain('Community B')
        // Several memberships: the header names the broader scope, not one community.
        expect(container.querySelector('.eyebrow')?.textContent).toBe('pages.myInvoices.allCommunities')
        expect(container.textContent).toContain('pages.invoices.pdfFailed')
        expect(container.textContent).toContain('common.openPdf')
        expect(container.textContent).not.toContain('pages.invoices.generateInvoice')
        expect(container.textContent).not.toContain('adminInvoices.delete')
        api.list.mockRejectedValue(new Error('Offline'))
        await act(async () => { await client.refetchQueries() })
        await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)) })
        expect(container.querySelectorAll('tbody tr')).toHaveLength(2)
        expect(container.querySelector('.warning-banner')).not.toBeNull()
        await act(async () => (container.querySelector('tbody a') as HTMLAnchorElement).click())
        expect(JSON.parse(container.querySelector('output')!.textContent!)).toEqual({ from: '/me/invoices' })
    })

    it('retains one pagination layer over the complete admin dataset and stable sorting/filtering', async () => {
        api.list.mockResolvedValue(Array.from({ length: 130 }, (_, i) => ({ ...invoice, id: `i${i}`, invoice_number: `INV-${i}`, total_chf: i.toFixed(2) })))
        const { container } = await mount(createElement(AdminInvoicesContent))
        expect(api.list).toHaveBeenCalledWith()
        expect(container.querySelectorAll('tbody tr')).toHaveLength(100)
        expect(container.querySelectorAll('.data-table')).toHaveLength(1)
        expect(container.querySelector('.data-table-footer')?.textContent).toContain('common.pagination.range')
        // One fixed page size: the footer offers no rows-per-page choice.
        expect(container.querySelector('.data-table-footer select')).toBeNull()
        const sort = [...container.querySelectorAll<HTMLButtonElement>('.data-table-sort')]
            .find(button => button.textContent?.includes('adminInvoices.total'))!
        await act(async () => sort.click())
        expect(container.querySelector('tbody tr')?.textContent).toContain('129.00 CHF')
        await act(async () => container.querySelector<HTMLButtonElement>('[aria-label="common.pagination.next"]')!.click())
        expect(container.querySelectorAll('tbody tr')).toHaveLength(30)
        expect(container.querySelector('tbody tr')?.textContent).toContain('29.00 CHF')
        const input = container.querySelector('input[type="search"]') as HTMLInputElement
        await act(async () => {
            Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, 'INV-29')
            input.dispatchEvent(new Event('input', { bubbles: true }))
        })
        await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)) })
        expect(container.querySelectorAll('tbody tr')).toHaveLength(1)
        expect(container.querySelector('tbody')?.textContent).toContain('29.00 CHF')
        expect(container.querySelector('.data-table-footer')).toBeNull()
    })
})
