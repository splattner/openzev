import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MantineProvider } from '@mantine/core'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Invoice, InvoicePeriodParticipantRow } from '../src/types/api'
import { waitForCondition } from './helpers/waitForCondition'

const api = vi.hoisted(() => ({ overview: vi.fn() }))

vi.mock('react-i18next', () => ({
    useTranslation: () => ({
        // Keep the params in the text so counts stay assertable.
        t: (key: string, params?: Record<string, unknown>) => (params ? `${key}(${JSON.stringify(params)})` : key),
        i18n: { language: 'en' },
    }),
}))
vi.mock('../src/lib/auth', () => ({
    useAuth: () => ({ user: { id: 1, role: 'admin', memberships: [] }, isAuthenticated: true, isLoading: false }),
}))
vi.mock('../src/lib/managedZev', () => {
    const scope = {
        selectedZevId: '42', relation: 'manager', isLoading: false, isError: false, isFetching: false,
        refetch: vi.fn(),
        selectedZev: { id: '42', name: 'Review ZEV', billing_interval: 'monthly', start_date: '2026-01-01' },
    }
    return { useManagedZev: () => scope, useOptionalManagedZev: () => scope }
})
vi.mock('../src/lib/toast', () => ({ useToast: () => ({ pushToast: vi.fn() }) }))
vi.mock('../src/lib/appSettings', () => ({
    useAppSettings: () => ({ settings: {} }),
    formatShortDate: (value: string) => value,
    formatDateTime: (value: string) => value,
}))
vi.mock('../src/lib/api/invoices', async importOriginal => ({
    ...await importOriginal(),
    fetchInvoicePeriodOverview: api.overview,
    openInvoicePdf: vi.fn(),
}))

import { InvoicesContent } from '../src/pages/InvoicesPage'

const invoice: Invoice = {
    id: 'i1', invoice_number: 'INV-1', zev: '42', zev_name: 'Review ZEV', participant: 'p1', participant_name: 'Anna',
    period_start: '2026-01-01', period_end: '2026-01-31', status: 'sent', total_chf: '10.00', pdf_url: '/stored.pdf',
}
const rows: InvoicePeriodParticipantRow[] = [
    // Sent invoice with a stored PDF.
    {
        participant_id: 'p1', participant_name: 'Anna', metering_data_complete: true, metering_points_total: 1,
        participant_kind: 'person', participant_name_addition: '', participant_valid_from: '2026-01-01',
        participant_valid_to: null, party_id: 'party-1', metering_point_labels: [],
        metering_points_with_data: 1, missing_meter_ids: [], generation_eligibility: null, invoice: { ...invoice },
    },
    // Draft without a document.
    {
        participant_id: 'p2', participant_name: 'Beat', metering_data_complete: true, metering_points_total: 1,
        participant_kind: 'person', participant_name_addition: '', participant_valid_from: '2026-01-01',
        participant_valid_to: null, party_id: 'party-1', metering_point_labels: [],
        metering_points_with_data: 1, missing_meter_ids: [], generation_eligibility: null,
        invoice: { ...invoice, id: 'i2', invoice_number: 'INV-2', participant: 'p2', participant_name: 'Beat', status: 'draft', pdf_url: null },
    },
    // Nothing generated yet, but eligible: the recommended batch action's target.
    {
        participant_id: 'p3', participant_name: 'Carla', metering_data_complete: true, metering_points_total: 1,
        participant_kind: 'person', participant_name_addition: '', participant_valid_from: '2026-01-01',
        participant_valid_to: null, party_id: 'party-1', metering_point_labels: [],
        metering_points_with_data: 1, missing_meter_ids: [], generation_eligibility: { state: 'eligible', invoice_id: null, invoice_number: null }, invoice: null,
    },
]

const cleanups: Array<() => void> = []
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))
beforeEach(() => {
    vi.clearAllMocks()
    api.overview.mockResolvedValue({ rows })
})

async function render(url = '/billing/invoices') {
    const container = document.createElement('div')
    document.body.append(container)
    const root = createRoot(container)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    await act(async () => root.render(
        createElement(MemoryRouter, { initialEntries: [url] },
            createElement(QueryClientProvider, { client },
                createElement(MantineProvider, null, createElement(InvoicesContent)),
            ),
        ),
    ))
    await waitForCondition(() => container.querySelectorAll('tbody tr').length === rows.length, 'the period rows')
    cleanups.push(() => { act(() => root.unmount()); client.clear(); container.remove() })
    return { container, client }
}

const segment = (container: HTMLElement, label: string) =>
    [...container.querySelectorAll<HTMLButtonElement>('.filter-tab')]
        .find((element) => element.textContent?.includes(label))!
const names = (container: HTMLElement) => [...container.querySelectorAll('tbody tr')]
    .map((row) => row.querySelector('td strong')?.textContent)
const batchButton = (container: HTMLElement) => container.querySelector('.invoice-batch-actions .button-primary')

describe('invoices page filters', () => {
    it('narrows the table to the rows a segment counts and restores them on a second press', async () => {
        const { container } = await render()
        expect(names(container)).toEqual(['Anna', 'Beat', 'Carla'])
        expect(segment(container, 'pages.invoices.filters.all').textContent).toContain('3')
        expect(segment(container, 'pages.invoices.filters.drafts').textContent).toContain('1')

        act(() => segment(container, 'pages.invoices.filters.drafts').click())
        await waitForCondition(() => names(container).length === 1, 'the filtered rows')
        expect(names(container)).toEqual(['Beat'])
        expect(segment(container, 'pages.invoices.filters.drafts').getAttribute('aria-pressed')).toBe('true')
        expect(container.querySelector('p.muted[role="status"]')?.textContent)
            .toContain('pages.invoices.filters.showing({"shown":1,"total":3})')

        // The pressed segment clears the filter.
        act(() => segment(container, 'pages.invoices.filters.drafts').click())
        await waitForCondition(() => names(container).length === 3, 'the cleared rows')
        expect(container.querySelector('p.muted[role="status"]')).toBeNull()
    })

    it('never lets a filter change what a batch action covers', async () => {
        const { container } = await render()
        // One eligible participant: the recommended action names that population.
        expect(batchButton(container)?.textContent).toContain('pages.invoices.batch.generateAllCount({"count":1})')

        act(() => segment(container, 'pages.invoices.filters.drafts').click())
        await waitForCondition(() => names(container).length === 1, 'the filtered rows')
        // The visible rows changed, the batch population did not.
        expect(batchButton(container)?.textContent).toContain('pages.invoices.batch.generateAllCount({"count":1})')
        expect(container.querySelector('p.muted[role="status"]')?.textContent)
            .toContain('pages.invoices.filters.showing({"shown":1,"total":3})')

        // The explicit clear action restores the period as well.
        act(() => [...container.querySelectorAll('button')].find((button) =>
            button.textContent === 'pages.invoices.filters.clear')!.click())
        await waitForCondition(() => names(container).length === 3, 'the cleared rows')
    })

    it('offers no empty segment, and explains a pressed segment that empties once', async () => {
        const { container, client } = await render()
        // Nothing is approved: the segment has nothing to show and is left out.
        expect(segment(container, 'pages.invoices.filters.approved')).toBeUndefined()
        expect(segment(container, 'pages.invoices.filters.all')).toBeDefined()

        // The draft is approved while its segment is pressed: one explanation,
        // with its clear action, and the segment can still be released.
        act(() => segment(container, 'pages.invoices.filters.drafts').click())
        await waitForCondition(() => names(container).length === 1, 'the filtered rows')
        api.overview.mockResolvedValue({ rows: rows.map((row) => row.participant_id === 'p2'
            ? { ...row, invoice: { ...row.invoice!, status: 'approved' } } : row) })
        await act(async () => { await client.invalidateQueries() })
        await waitForCondition(() => container.querySelector('tbody') === null, 'the empty filter state')
        expect(container.textContent).toContain('pages.invoices.filters.noMatches')
        expect(container.textContent).not.toContain('pages.invoices.filters.showing')
        expect(segment(container, 'pages.invoices.filters.drafts').getAttribute('aria-pressed')).toBe('true')
        act(() => [...container.querySelectorAll('button')].find((button) =>
            button.textContent === 'pages.invoices.filters.clear')!.click())
        await waitForCondition(() => names(container).length === 3, 'the cleared rows')
    })

    it('drops the filter when the period time frame changes', async () => {
        const { container } = await render()
        act(() => segment(container, 'pages.invoices.filters.sent').click())
        await waitForCondition(() => names(container).length === 1, 'the filtered rows')

        act(() => container.querySelector<HTMLButtonElement>('button[aria-label="pages.invoices.prevPeriod"]')!.click())
        await waitForCondition(() => names(container).length === 3, 'the next period')
        expect(segment(container, 'pages.invoices.filters.sent').getAttribute('aria-pressed')).toBe('false')
        expect(segment(container, 'pages.invoices.filters.all').getAttribute('aria-pressed')).toBe('true')
    })

    it('shows a linked range that is no billing period, but creates no invoice for it', async () => {
        const { container } = await render('/billing/invoices?period_start=2026-02-03&period_end=2026-02-20')
        expect(container.textContent).toContain('pages.invoices.unalignedPeriod.notice')
        expect(container.querySelector('.period-selector .badge-warning')?.textContent).toContain('common.periodSelector.notBillingPeriod')
        // Nothing generates here: not the batch, not the row.
        expect(batchButton(container)?.textContent).toContain('pages.invoices.batch.approveAllCount')
        expect(container.textContent).not.toContain('pages.invoices.batch.generateAllCount')
        expect(container.textContent).not.toContain('pages.invoices.generateInvoice')
        // The whole period around it is one click away.
        const show = [...container.querySelectorAll('button')]
            .find((button) => button.textContent?.startsWith('pages.invoices.unalignedPeriod.show'))!
        expect(show.textContent).toContain('February 2026')
        await act(async () => show.click())
        await waitForCondition(() => api.overview.mock.calls.some(([params]) => params.period_start === '2026-02-01'), 'the whole period')
        expect(api.overview).toHaveBeenLastCalledWith(expect.objectContaining({ period_start: '2026-02-01', period_end: '2026-02-28' }))
        await waitForCondition(() => batchButton(container) !== null, 'generation offered again')
        expect(container.textContent).not.toContain('pages.invoices.unalignedPeriod.notice')
    })
})
