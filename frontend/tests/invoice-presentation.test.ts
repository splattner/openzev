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

import { InvoicePdfCell, InvoiceStatusBadge } from '../src/components/InvoicePresentation'
import { InvoicePeriodRowsTable } from '../src/features/invoices/InvoicePeriodRowsTable'
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
        ['draft', '0.00', 'invoice.status.draft'],
        ['approved', '0.00', 'invoice.status.approved'],
        ['sent', '0.00', 'invoice.status.sent'],
        ['sent', '1.00', 'invoice.status.partlyPaid'],
        ['paid', '12.30', 'invoice.status.paid'],
        ['cancelled', '0.00', 'invoice.status.cancelled'],
        ['future-status', '0.00', 'invoice.status.future-status'],
    ] as const)('preserves %s wording in the plain status label with paid amount %s', async (status, paidChf, label) => {
        const { container } = await mount(createElement(InvoiceStatusBadge, { status, paidChf, variant: 'plain' }))
        expect(container.textContent).toContain(label)
        const className = status === 'cancelled' ? 'error-text' : label === 'invoice.status.partlyPaid' ? 'badge badge-info'
            : ['draft', 'approved', 'sent', 'paid'].includes(status) ? `invoice-status-${status}` : 'muted'
        expect(container.querySelector('span')?.className).toBe(className)
    })

    it.each([
        ['pending', null, 'pages.invoices.pdfGenerating'],
        ['failed', null, 'pages.invoices.pdfFailed'],
        ['none', null, 'pages.invoices.pdfMissing'],
        ['ready', '/stored.pdf', 'common.openPdf'],
        ['failed', '/stored.pdf', 'common.openPdf'],
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

    it('shows only the load error for an initial admin invoice failure', async () => {
        api.list.mockRejectedValue(new Error('Offline'))
        const { container } = await mount(createElement(AdminInvoicesContent))
        expect(container.textContent).toContain('adminInvoices.loadError')
        expect(container.textContent).not.toContain('adminInvoices.empty')
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
