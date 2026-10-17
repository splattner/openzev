import { describe, expect, it, vi } from 'vitest'
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MantineProvider } from '@mantine/core'
import type { Invoice, InvoicePeriodParticipantRow } from '../src/types/api'
import { isPartlyPaid } from '../src/features/invoices/invoiceStatus'
import { invoiceRowProgress } from '../src/features/invoices/invoiceRowState'
import { InvoicePaymentsCard } from '../src/features/invoices/InvoicePaymentsCard'
import { ToastProvider } from '../src/lib/toast'

vi.mock('react-i18next', () => ({
    useTranslation: () => ({
        t: (k: string) => k,
        i18n: { language: 'en', changeLanguage: vi.fn() },
    }),
}))

vi.mock('../src/lib/appSettings', () => ({
    useAppSettings: () => ({ settings: {}, isLoading: false }),
    formatShortDate: (v: string | null | undefined) => v ?? '',
    toDayJsDateFormat: () => 'DD.MM.YYYY',
}))

const recordPayment = vi.fn()
const markInvoicePaid = vi.fn()
vi.mock('../src/lib/api/invoices', () => ({
    recordPayment: (...args: unknown[]) => recordPayment(...args),
    markInvoicePaid: (...args: unknown[]) => markInvoicePaid(...args),
    deletePayment: vi.fn(),
}))

const invoice: Invoice = {
    id: 'i1', invoice_number: 'INV-1', zev: 'z1', zev_name: 'Community A', participant: 'p1', participant_name: 'Anna',
    period_start: '2026-02-01', period_end: '2026-02-28', status: 'sent', total_chf: '100.00',
    paid_chf: '0.00', outstanding_chf: '100.00', payments: [],
}

const row: InvoicePeriodParticipantRow = {
    participant_id: 'p1', participant_name: 'Anna', participant_email: 'anna@example.test', metering_data_complete: true,
    participant_kind: 'person', participant_name_addition: '', participant_valid_from: '2026-01-01',
    participant_valid_to: null, party_id: 'party-1', metering_point_labels: [],
    metering_points_total: 1, metering_points_with_data: 1, missing_meter_ids: [], generation_eligibility: null,
    invoice,
}

const paidStep = (inv: Invoice) => invoiceRowProgress({ ...row, invoice: inv })?.find((step) => step.step === 'paid')

describe('partly paid invoices', () => {
    it('is a sent invoice with some money received', () => {
        expect(isPartlyPaid({ status: 'sent', paid_chf: '20.00' })).toBe(true)
        expect(isPartlyPaid({ status: 'sent', paid_chf: '0.00' })).toBe(false)
        expect(isPartlyPaid({ status: 'paid', paid_chf: '100.00' })).toBe(false)
        expect(isPartlyPaid({ status: 'sent' })).toBe(false)
    })

    it('shows the paid step under way rather than open', () => {
        expect(paidStep(invoice)).toEqual({ step: 'paid', state: 'open' })
        expect(paidStep({ ...invoice, paid_chf: '20.00', outstanding_chf: '80.00' }))
            .toEqual({ step: 'paid', state: 'active', reason: 'partlyPaid' })
        expect(paidStep({ ...invoice, status: 'paid', paid_chf: '100.00' })).toEqual({ step: 'paid', state: 'done' })
    })
})

async function renderCard(inv: Invoice, canManage = true) {
    const container = document.createElement('div')
    document.body.appendChild(container)
    const onChanged = vi.fn()
    const root = createRoot(container)
    await act(async () => {
        root.render(
            createElement(QueryClientProvider, { client: new QueryClient() },
                createElement(MantineProvider, null,
                    createElement(ToastProvider, null,
                        createElement(InvoicePaymentsCard, { invoice: inv, canManage, onChanged })))),
        )
    })
    return { container, onChanged, root }
}

const buttons = (container: HTMLElement) => Array.from(container.querySelectorAll('button'))
const byText = (container: HTMLElement, text: string) => buttons(container).find((b) => b.textContent?.includes(text))

describe('InvoicePaymentsCard', () => {
    it('lists payments with the received and outstanding amounts', async () => {
        const { container, root } = await renderCard({
            ...invoice, paid_chf: '40.00', outstanding_chf: '60.00',
            payments: [{
                id: 'pay1', invoice: 'i1', amount_chf: '40.00', paid_on: '2026-03-01', note: 'E-Banking',
                source: 'manual', created_by_name: 'Olga', created_at: '2026-03-01T08:00:00Z',
            }],
        })
        expect(container.textContent).toContain('pages.invoiceDetail.payments.summary')
        expect(container.textContent).toContain('E-Banking')
        expect(byText(container, 'pages.invoiceDetail.payments.markRestPaid')).toBeTruthy()
        act(() => root.unmount())
        container.remove()
    })

    it('records a partial payment through the dialog', async () => {
        recordPayment.mockResolvedValue({ ...invoice, paid_chf: '100.00', outstanding_chf: '0.00' })
        const { container, onChanged, root } = await renderCard(invoice)
        await act(async () => { byText(container, 'pages.invoiceDetail.payments.record')?.click() })
        const form = document.querySelector('form') as HTMLFormElement
        expect(form).toBeTruthy()
        expect((form.querySelector('input[type="number"]') as HTMLInputElement).value).toBe('100.00')
        await act(async () => { form.requestSubmit() })
        await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
        expect(recordPayment).toHaveBeenCalledWith('i1', expect.objectContaining({ amount_chf: '100.00', note: '' }))
        expect(onChanged).toHaveBeenCalled()
        act(() => root.unmount())
        container.remove()
    })

    it('offers only mark-paid for a payout invoice', async () => {
        const { container, root } = await renderCard({ ...invoice, total_chf: '-40.00', outstanding_chf: '-40.00' })
        expect(byText(container, 'pages.invoiceDetail.payments.record')).toBeUndefined()
        expect(byText(container, 'pages.invoices.markPaid')).toBeTruthy()
        act(() => root.unmount())
        container.remove()
    })

    it('stays read-only for a viewer and hides an empty card', async () => {
        const { container, root } = await renderCard(invoice, false)
        expect(container.querySelector('section')).toBeNull()
        act(() => root.unmount())
        container.remove()
    })
})
