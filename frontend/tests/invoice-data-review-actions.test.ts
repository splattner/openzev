import { act, createElement, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MantineProvider } from '@mantine/core'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { InvoiceDataReviewActions } from '../src/features/invoices/InvoiceDataReviewActions'
import { ToastProvider } from '../src/lib/toast'
import type { Invoice } from '../src/types/api'

const api = vi.hoisted(() => ({ replace: vi.fn(), generate: vi.fn(), correct: vi.fn(), preview: vi.fn() }))
const setSelectedZevId = vi.hoisted(() => vi.fn())
vi.mock('../src/lib/managedZev', () => ({ useManagedZev: () => ({ setSelectedZevId }) }))
vi.mock('../src/lib/api/invoices', () => ({ replaceInvoice: api.replace, generateInvoice: api.generate, correctInvoice: api.correct, previewInvoiceCalculation: api.preview }))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string, values?: Record<string, unknown>) => values ? `${key} ${JSON.stringify(values)}` : key }) }))
vi.mock('../src/lib/auth', () => ({ useAuth: () => ({ user: { id: 1 } }) }))

const base: Invoice = {
    id: 'inv-1', invoice_number: 'INV-1', zev: 'z1', zev_name: 'Community', participant: 'p1', participant_name: 'Anna',
    status: 'approved', period_start: '2026-02-01', period_end: '2026-02-28', total_chf: '100.00', paid_chf: '0.00',
    total_local_kwh: '502.8933', total_grid_kwh: '161.7506', total_feed_in_kwh: '0.0000',
    payments: [], needs_data_review: true, open_data_impact_count: 1,
}
const cleanups: Array<() => void> = []
beforeEach(() => {
    vi.resetAllMocks()
    api.preview.mockResolvedValue({ total_chf: '100.00', total_local_kwh: '502.8911', total_grid_kwh: '161.7528', total_feed_in_kwh: '0.0000' })
})
afterEach(() => cleanups.splice(0).forEach(cleanup => cleanup()))

const settle = () => new Promise(resolve => setTimeout(resolve, 10))
async function flush() { await act(async () => { await settle() }) }

async function mount(invoice = base, canManage = true) {
    const container = document.createElement('div')
    document.body.append(container)
    const root = createRoot(container)
    const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
    const changed = vi.fn()
    function Harness() {
        const [current, setCurrent] = useState(invoice)
        const location = useLocation()
        return createElement('div', null,
            createElement(InvoiceDataReviewActions, { invoice: current, canManage, onChanged: (updated) => { changed(updated); setCurrent(updated) } }),
            createElement('output', null, JSON.stringify({ pathname: location.pathname, state: location.state })),
        )
    }
    await act(async () => root.render(createElement(MemoryRouter, {
        initialEntries: [{ pathname: '/billing/invoices/inv-1', state: { from: '/billing/invoices', period_start: base.period_start, period_end: base.period_end } }],
    }, createElement(QueryClientProvider, { client }, createElement(MantineProvider, null, createElement(ToastProvider, null, createElement(Harness)))))))
    await flush()
    cleanups.push(() => { act(() => root.unmount()); client.clear(); container.remove() })
    return { container, changed, client }
}
const button = (label: string, within: ParentNode = document) => Array.from(within.querySelectorAll('button')).find(node => node.textContent === label)!
async function click(node: HTMLButtonElement) {
    expect(node).toBeTruthy()
    await act(async () => { node.click(); await settle() })
}

describe('invoice correction resolution', () => {
    it('replaces an unpaid issued invoice with one confirmation and one request', async () => {
        const replacement = { ...base, id: 'inv-2', status: 'draft', needs_data_review: false }
        api.replace.mockResolvedValue(replacement)
        const { container, changed } = await mount()
        await click(button('pages.invoices.dataReview.replace', container))
        expect(api.replace).not.toHaveBeenCalled()
        await click(button('pages.invoices.dataReview.replace', document.querySelector('[role="dialog"]')!))
        expect(api.replace).toHaveBeenCalledExactlyOnceWith('inv-1')
        expect(changed).toHaveBeenCalledWith(replacement)
        expect(api.generate).not.toHaveBeenCalled()
        const location = JSON.parse(container.querySelector('output')!.textContent!)
        expect(location.pathname).toBe('/billing/invoices/inv-2')
        expect(location.state.period_start).toBe(base.period_start)
        expect(location.state.recalculation).toEqual({ invoiceId: 'inv-2', before: { invoice_number: base.invoice_number, total_chf: base.total_chf, total_local_kwh: base.total_local_kwh, total_grid_kwh: base.total_grid_kwh, total_feed_in_kwh: base.total_feed_in_kwh } })
    })

    it('shows the expected total and a compact energy shift before the action', async () => {
        const { container } = await mount()
        expect(api.preview.mock.calls[0][0]).toBe('inv-1')
        expect(container.textContent).toContain('pages.invoices.dataReview.previewUnchanged')
        expect(container.textContent).toContain('pages.invoices.dataReview.energyShift')
        expect(container.textContent).toContain('0.0022')
        expect(container.textContent).not.toContain('pages.invoices.dataReview.previewDifference')
        expect(container.querySelector('[role="status"] strong')?.textContent).toBe('CHF 100.00')
        expect(api.replace).not.toHaveBeenCalled()
        expect(api.generate).not.toHaveBeenCalled()
    })

    it('shows changed amounts and individual quantities when energy is added', async () => {
        api.preview.mockResolvedValue({ total_chf: '101.00', total_local_kwh: '503.8933', total_grid_kwh: base.total_grid_kwh, total_feed_in_kwh: '1.0000' })
        const { container } = await mount()
        expect(container.textContent).toContain('pages.invoices.dataReview.previewAmount')
        expect(container.textContent).toContain('pages.invoices.dataReview.energyChanged')
        expect(container.textContent).not.toContain('pages.invoices.dataReview.energyShift')
    })

    it.each([['100.01', '+CHF 0.01'], ['99.99', '−CHF 0.01']])('shows a signed one-cent difference for %s without a badge or strike-through', async (total, difference) => {
        api.preview.mockResolvedValue({ total_chf: total, total_local_kwh: base.total_local_kwh, total_grid_kwh: base.total_grid_kwh, total_feed_in_kwh: base.total_feed_in_kwh })
        const { container } = await mount()
        const comparison = container.querySelector('[role="status"]')!
        expect(comparison.textContent).toContain('CHF 100.00')
        expect(comparison.textContent).toContain(`pages.invoices.dataReview.previewDifference {"amount":"${difference}"}`)
        expect(comparison.querySelector('strong')?.textContent).toBe(`CHF ${total}`)
        expect(comparison.querySelector('s, del, [class*="badge"]')).toBeNull()
        expect(button('pages.invoices.dataReview.replace', container)).toBeTruthy()
    })

    it('blocks generation while preview loads, then allows retry after a failure', async () => {
        let reject!: (error: Error) => void
        api.preview.mockReturnValueOnce(new Promise((_resolve, rejectPromise) => { reject = rejectPromise }))
        const { container } = await mount()
        expect(button('pages.invoices.dataReview.replace', container).disabled).toBe(true)
        await act(async () => { reject(new Error('Offline')); await settle() })
        expect(container.textContent).toContain('pages.invoices.dataReview.previewFailed')
        expect(button('pages.invoices.dataReview.replace', container).disabled).toBe(true)
        await click(button('common.retry', container))
        expect(api.preview).toHaveBeenCalledTimes(2)
        expect(button('pages.invoices.dataReview.replace', container).disabled).toBe(false)
        expect(api.replace).not.toHaveBeenCalled()
    })

    it('keeps the review open on replacement failure and allows retry', async () => {
        api.replace.mockRejectedValue(new Error('Offline'))
        const { container, changed } = await mount()
        await click(button('pages.invoices.dataReview.replace', container))
        await click(button('pages.invoices.dataReview.replace', document.querySelector('[role="dialog"]')!))
        expect(changed).not.toHaveBeenCalled()
        expect(document.querySelector('[role="dialog"]')).toBeNull()
        await click(button('pages.invoices.dataReview.replace', container))
        expect(document.querySelector('[role="dialog"]')).not.toBeNull()
        expect(api.generate).not.toHaveBeenCalled()
    })

    it('opens tariff recovery in the invoice community instead of the header community', async () => {
        api.preview.mockRejectedValue({ isAxiosError: true, response: { data: { code: 'invalid_dynamic_tariff' } } })
        const { container } = await mount()
        await click(button('pages.invoices.emptyState.tariffsAction', container))
        expect(setSelectedZevId).toHaveBeenCalledExactlyOnceWith(base.zev)
        expect(JSON.parse(container.querySelector('output')!.textContent!).pathname).toBe('/tariffs')
        expect(api.replace).not.toHaveBeenCalled()
    })

    it('also blocks an already open confirmation while its preview refresh fails', async () => {
        const { container, client } = await mount()
        await click(button('pages.invoices.dataReview.replace', container))
        let reject!: (error: Error) => void
        api.preview.mockReturnValueOnce(new Promise((_resolve, rejectPromise) => { reject = rejectPromise }))
        await act(async () => { void client.invalidateQueries({ queryKey: ['invoices', 'detail', base.id] }); await settle() })
        const confirm = button('pages.invoices.dataReview.replace', document.querySelector('[role="dialog"]')!)
        expect(confirm.disabled).toBe(true)
        await act(async () => { reject(new Error('Offline')); await settle() })
        expect(confirm.disabled).toBe(true)
        await click(confirm)
        expect(api.replace).not.toHaveBeenCalled()
    })

    it('regenerates a draft only after confirmation', async () => {
        api.generate.mockResolvedValue({ ...base, id: 'replacement', status: 'draft', needs_data_review: false })
        const { container } = await mount({ ...base, status: 'draft' })
        await click(button('pages.invoices.regenerateInvoice', container))
        expect(api.generate).not.toHaveBeenCalled()
        await click(button('pages.invoices.regenerateInvoice', document.querySelector('[role="dialog"]')!))
        expect(api.generate).toHaveBeenCalledExactlyOnceWith({ participant_id: 'p1', period_start: base.period_start, period_end: base.period_end })
        expect(api.replace).not.toHaveBeenCalled()
    })

    it.each(['paid', 'sent'])('opens the existing credit-note dialog for a %s invoice with payments', async (status) => {
        const { container } = await mount({ ...base, status, paid_chf: '40.00' })
        expect(button('pages.invoices.dataReview.replace', container)).toBeUndefined()
        await click(button('pages.invoiceDetail.credits.correct', container))
        expect(document.querySelector<HTMLInputElement>('input[value="reversal"]')?.checked).toBe(true)
        expect(document.querySelector('textarea')).not.toBeNull()
        expect(api.correct).not.toHaveBeenCalled()
    })

    it('offers no write actions to viewers or disabled-community managers', async () => {
        const { container } = await mount(base, false)
        expect(container.querySelector('button')).toBeNull()
        expect(api.preview).not.toHaveBeenCalled()
    })

    it('does not guess that an invoice with unknown payments can be replaced', async () => {
        const { container } = await mount({ ...base, payments: undefined })
        expect(container.querySelector('button')).toBeNull()
    })

    it('does not offer another replacement when one already exists', async () => {
        const { container } = await mount({ ...base, status: 'cancelled', replaced_by: { id: 'new', invoice_number: 'NEW', status: 'draft' } })
        expect(container.querySelector('button')).toBeNull()
    })
})
