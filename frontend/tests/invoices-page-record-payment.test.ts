import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MantineProvider } from '@mantine/core'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Invoice, InvoicePeriodParticipantRow } from '../src/types/api'
import { waitForCondition } from './helpers/waitForCondition'

const api = vi.hoisted(() => ({ overview: vi.fn(), recordPayment: vi.fn(), markPaid: vi.fn(), pushToast: vi.fn() }))

vi.mock('react-i18next', () => ({
    useTranslation: () => ({
        // Keep the params in the text so interpolation stays assertable.
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
vi.mock('../src/lib/toast', () => ({ useToast: () => ({ pushToast: api.pushToast }) }))
vi.mock('../src/lib/appSettings', () => ({
    useAppSettings: () => ({ settings: {} }),
    formatShortDate: (value: string) => value,
    formatDateTime: (value: string) => value,
    toDayJsDateFormat: () => 'DD.MM.YYYY',
}))
vi.mock('../src/lib/api/invoices', async importOriginal => ({
    ...await importOriginal(),
    fetchInvoicePeriodOverview: api.overview,
    recordPayment: api.recordPayment,
    markInvoicePaid: api.markPaid,
    openInvoicePdf: vi.fn(),
}))

import { InvoicesContent } from '../src/pages/InvoicesPage'

const invoice: Invoice = {
    id: 'i1', invoice_number: 'INV-9', zev: '42', zev_name: 'Review ZEV', participant: 'p1', participant_name: 'Anna',
    period_start: '2026-01-01', period_end: '2026-01-31', status: 'sent', total_chf: '100.00',
    paid_chf: '25.00', outstanding_chf: '75.00', amount_due_chf: '100.00', pdf_url: null, email_logs: [],
}
const settledInvoice: Invoice = {
    ...invoice, status: 'paid', paid_chf: '100.00', outstanding_chf: '0.00',
}
const rows: InvoicePeriodParticipantRow[] = [{
    participant_id: 'p1', participant_name: 'Anna', metering_data_complete: true, metering_points_total: 1,
    participant_kind: 'person', participant_name_addition: '', participant_valid_from: '2026-01-01',
    participant_valid_to: null, party_id: 'party-1', metering_point_labels: [],
    metering_points_with_data: 1, missing_meter_ids: [], generation_eligibility: null, invoice: { ...invoice },
}]
const settledRows: InvoicePeriodParticipantRow[] = [{
    ...rows[0], invoice: { ...settledInvoice },
}]
const twoRows: InvoicePeriodParticipantRow[] = [rows[0], {
    ...rows[0], participant_id: 'p2', participant_name: 'Ben',
    invoice: { ...invoice, id: 'i2', invoice_number: 'INV-10', participant: 'p2' },
}]

const cleanups: Array<() => void> = []
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))
beforeEach(() => {
    vi.clearAllMocks()
    api.overview.mockResolvedValue({ rows })
    api.recordPayment.mockImplementation(async () => {
        api.overview.mockResolvedValue({ rows: settledRows })
        return { ...settledInvoice }
    })
})

async function render(expectedRows = rows.length) {
    const container = document.createElement('div')
    document.body.append(container)
    const root = createRoot(container)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    cleanups.push(() => { act(() => root.unmount()); client.clear(); container.remove() })
    await act(async () => root.render(
        createElement(MemoryRouter, { initialEntries: ['/billing/invoices'] },
            createElement(QueryClientProvider, { client },
                createElement(MantineProvider, null, createElement(InvoicesContent)),
            ),
        ),
    ))
    await waitForCondition(() => container.querySelectorAll('tbody tr').length === expectedRows, 'the period rows')
    return { container, client }
}

async function paymentMenuItem(container: HTMLElement, rowIndex = 0) {
    await waitForCondition(() => document.querySelectorAll('[role="menuitem"]').length === 0, 'the previous menu to close')
    const trigger = container.querySelectorAll<HTMLButtonElement>('tbody tr button[aria-haspopup="menu"]')[rowIndex]
    await act(async () => { trigger.click() })
    let item: HTMLButtonElement | undefined
    await waitForCondition(() => {
        item = [...document.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')]
            .find(node => node.textContent === 'pages.invoiceDetail.payments.record')
        return item !== undefined
    }, 'the record-payment menu item')
    return item!
}

describe('recording a payment from the period row menu', () => {
    it('books the outstanding amount and closes the dialog', async () => {
        const { container } = await render()

        // The row's More menu offers the payment action for a partly paid invoice.
        const menuItem = await paymentMenuItem(container)
        await act(async () => { menuItem.click() })

        // The dialog names the invoice it was opened for and defaults to the outstanding amount.
        const dialog = document.querySelector('.form-modal')!
        expect(dialog.textContent).toContain('pages.invoiceDetail.payments.recordTitle')
        expect(dialog.textContent).toContain('pages.invoiceDetail.payments.invoiceContext({"number":"INV-9"})')
        expect(dialog.textContent).toContain('pages.invoiceDetail.payments.outstandingHint')
        expect(dialog.querySelector<HTMLInputElement>('input[type="number"]')!.value).toBe('75.00')

        await act(async () => { dialog.querySelector('form')!.requestSubmit() })
        await waitForCondition(() => api.recordPayment.mock.calls.length === 1, 'the recorded payment')
        expect(api.recordPayment).toHaveBeenCalledWith('i1', expect.objectContaining({ amount_chf: '75.00', note: '' }))
        expect(api.pushToast).toHaveBeenCalledWith('pages.invoiceDetail.payments.recorded', 'success')

        // The dialog closes and the period reloads with the settled balance.
        await waitForCondition(() => document.querySelector('.form-modal') === null, 'the closed dialog')
        await waitForCondition(() => api.overview.mock.calls.length > 1, 'the refreshed period')
        await waitForCondition(
            () => container.textContent?.includes('100.00') && !container.textContent?.includes('75.00'),
            'the settled balance',
        )
        await act(async () => {
            container.querySelector<HTMLButtonElement>('tbody tr button[aria-haspopup="menu"]')!.click()
        })
        await waitForCondition(
            () => [...document.querySelectorAll<HTMLElement>('[role="menuitem"]')].length > 0,
            'the reopened menu',
        )
        expect(
            [...document.querySelectorAll<HTMLElement>('[role="menuitem"]')].map((node) => node.textContent),
        ).not.toContain('pages.invoiceDetail.payments.record')
    })

    it('locks other invoice menus while a dismissed payment is still pending', async () => {
        let resolve!: (value: Invoice) => void
        api.recordPayment.mockReturnValue(new Promise<Invoice>(done => { resolve = done }))
        api.overview.mockResolvedValue({ rows: twoRows })
        const { container } = await render(2)
        const item = await paymentMenuItem(container)
        await act(async () => { item.click() })
        const dialog = document.querySelector('.form-modal')!
        await act(async () => { dialog.querySelector('form')!.requestSubmit() })
        await waitForCondition(() => api.recordPayment.mock.calls.length === 1, 'the pending payment')
        await waitForCondition(() => dialog.querySelector<HTMLButtonElement>('button[type="submit"]')!.disabled, 'the disabled payment form')
        const markPaidButtons = [...container.querySelectorAll<HTMLButtonElement>('tbody tr button')]
            .filter(button => button.textContent === 'pages.invoices.markRestPaid')
        expect(markPaidButtons).toHaveLength(2)
        for (const button of markPaidButtons) {
            expect(button.disabled).toBe(true)
            await act(async () => { button.click() })
        }
        expect(api.markPaid).not.toHaveBeenCalled()
        // Even a retained form cannot resubmit while the request is open.
        await act(async () => { dialog.querySelector('form')!.requestSubmit() })
        await act(async () => { dialog.querySelector<HTMLButtonElement>('.form-modal-close')!.click() })
        const otherItem = await paymentMenuItem(container, 1)
        expect(otherItem.disabled).toBe(true)
        await act(async () => { otherItem.click() })
        expect(document.querySelector('.form-modal')).toBeNull()
        expect(api.recordPayment).toHaveBeenCalledTimes(1)
        await act(async () => { resolve(settledInvoice) })
        await waitForCondition(() => !otherItem.disabled, 'payment actions to unlock')
    })

    it('locks both actions across rows and an open dialog while mark-paid is pending', async () => {
        let resolve!: (value: Invoice) => void
        api.markPaid.mockReturnValue(new Promise<Invoice>(done => { resolve = done }))
        api.overview.mockResolvedValue({ rows: twoRows })
        const { container } = await render(2)
        const item = await paymentMenuItem(container)
        await act(async () => { item.click() })
        const dialog = document.querySelector('.form-modal')!
        const markPaidButtons = [...container.querySelectorAll<HTMLButtonElement>('tbody tr button')]
            .filter(button => button.textContent === 'pages.invoices.markRestPaid')
        await act(async () => { markPaidButtons[0].click() })
        await waitForCondition(() => dialog.querySelector<HTMLButtonElement>('button[type="submit"]')!.disabled, 'the locked payment dialog')
        expect(api.markPaid).toHaveBeenCalledWith('i1')
        for (const button of markPaidButtons) {
            expect(button.disabled).toBe(true)
            await act(async () => { button.click() })
        }
        await act(async () => { dialog.querySelector('form')!.requestSubmit() })
        expect(api.markPaid).toHaveBeenCalledTimes(1)
        expect(api.recordPayment).not.toHaveBeenCalled()
        await act(async () => { dialog.querySelector<HTMLButtonElement>('.form-modal-close')!.click() })
        const otherItem = await paymentMenuItem(container, 1)
        expect(otherItem.disabled).toBe(true)
        await act(async () => { resolve(settledInvoice) })
        await waitForCondition(() => !otherItem.disabled && markPaidButtons.every(button => !button.disabled), 'both payment actions to unlock')
    })

    it.each(['success', 'error'])('keeps %s completion in its submitting period', async outcome => {
        let resolve!: (value: Invoice) => void
        let reject!: (error: Error) => void
        api.recordPayment.mockReturnValue(new Promise<Invoice>((done, fail) => { resolve = done; reject = fail }))
        const { container, client } = await render()
        const invalidate = vi.spyOn(client, 'invalidateQueries')
        const item = await paymentMenuItem(container)
        await act(async () => { item.click() })
        await act(async () => { document.querySelector('.form-modal form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })) })
        await waitForCondition(() => api.recordPayment.mock.calls.length === 1, 'the pending payment')
        const submitted = api.overview.mock.calls[0][0]
        await act(async () => { document.querySelector<HTMLButtonElement>('.form-modal-close')!.click() })
        await act(async () => { container.querySelector<HTMLButtonElement>('button[aria-label="pages.invoices.prevPeriod"]')!.click() })
        await waitForCondition(() => api.overview.mock.calls.some(([params]) => params.period_start !== submitted.period_start), 'the previous period')
        invalidate.mockClear()
        api.pushToast.mockClear()
        await act(async () => {
            if (outcome === 'success') resolve(settledInvoice)
            else reject(new Error('network down'))
        })
        if (outcome === 'success') {
            expect(invalidate.mock.calls.map(([filters]) => filters?.queryKey)).toEqual(expect.arrayContaining([
                ['invoices', 'period-overview', '42', submitted.period_start, submitted.period_end],
                ['invoices', 'readiness', '42'],
                ['invoices', 'readiness-list', '42'],
                ['invoices', 'attention', '42'],
            ]))
            expect(invalidate.mock.calls.filter(([filters]) => filters?.queryKey?.[1] === 'period-overview')).toHaveLength(1)
        }
        expect(api.pushToast).not.toHaveBeenCalled()
    })
})
