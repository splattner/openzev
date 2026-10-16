import { describe, expect, it, vi } from 'vitest'
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MantineProvider } from '@mantine/core'
import type { Credit, Invoice } from '../src/types/api'
import { canCorrectInvoice, creditableChf } from '../src/features/invoices/invoiceCredits'
import { InvoiceCreditsCard } from '../src/features/invoices/InvoiceCreditsCard'
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

const correctInvoice = vi.fn()
vi.mock('../src/lib/api/invoices', () => ({
    correctInvoice: (...args: unknown[]) => correctInvoice(...args),
    openCreditPdf: vi.fn(),
    recordPayment: vi.fn(),
    markInvoicePaid: vi.fn(),
    deletePayment: vi.fn(),
}))

const credit: Credit = {
    id: 'c1', credit_number: 'CN-00001', zev: 'z1', participant: 'p1', participant_name: 'Anna', kind: 'adjustment',
    source_invoice: 'i1', source_invoice_number: 'INV-1', reason: 'Overcharged', amount_chf: '10.00',
    vat_mode: 'not_registered', vat_rate: '0.0000', vat_chf: '0.00', embedded_vat_chf: null, remaining_chf: '10.00',
    refunded_chf: '0.00', refunded_on: null, refund_note: '', applications: [],
    status: 'open', pdf_url: 'http://x/pdf/', pdf_status: 'ready', created_by_name: 'Olga', created_at: '2026-03-02T08:00:00Z',
}

const paid: Invoice = {
    id: 'i1', invoice_number: 'INV-1', zev: 'z1', zev_name: 'Community A', participant: 'p1', participant_name: 'Anna',
    period_start: '2026-02-01', period_end: '2026-02-28', status: 'paid', total_chf: '100.00',
    paid_chf: '100.00', outstanding_chf: '0.00', payments: [], credits: [],
}

describe('creditableChf', () => {
    it('is what was received less what is credited', () => {
        expect(creditableChf(paid)).toBe(100)
        expect(creditableChf({ ...paid, credits: [credit] })).toBe(90)
        expect(creditableChf({ paid_chf: undefined, credits: undefined })).toBe(0)
    })
})

describe('canCorrectInvoice', () => {
    it('offers it for a paid invoice, or a sent one with payments', () => {
        expect(canCorrectInvoice(paid, true)).toBe(true)
        expect(canCorrectInvoice({ ...paid, status: 'sent', paid_chf: '20.00' }, true)).toBe(true)
    })

    it('does not for a viewer, an unpaid, cancelled or payout invoice, or one fully credited', () => {
        expect(canCorrectInvoice(paid, false)).toBe(false)
        expect(canCorrectInvoice({ ...paid, status: 'sent', paid_chf: '0.00' }, true)).toBe(false)
        expect(canCorrectInvoice({ ...paid, status: 'cancelled' }, true)).toBe(false)
        expect(canCorrectInvoice({ ...paid, total_chf: '-40.00', paid_chf: '0.00' }, true)).toBe(false)
        expect(canCorrectInvoice({ ...paid, credits: [{ ...credit, amount_chf: '100.00' }] }, true)).toBe(false)
    })
})

async function render(node: ReturnType<typeof createElement>) {
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)
    await act(async () => {
        root.render(
            createElement(QueryClientProvider, { client: new QueryClient() },
                createElement(MantineProvider, null, createElement(ToastProvider, null, node))),
        )
    })
    return { container, root }
}

const byText = (container: ParentNode, text: string) =>
    Array.from(container.querySelectorAll('button')).find((b) => b.textContent?.includes(text))

describe('InvoiceCreditsCard', () => {
    it('lists the credit notes with their PDF action', async () => {
        const { container, root } = await render(createElement(InvoiceCreditsCard, {
            invoice: { ...paid, credits: [credit] }, canManage: false, onChanged: vi.fn(),
        }))
        expect(container.textContent).toContain('CN-00001')
        expect(container.textContent).toContain('Overcharged')
        expect(container.querySelector('button[aria-label="pages.invoiceDetail.credits.openPdf"]')).toBeTruthy()
        expect(byText(container, 'pages.invoiceDetail.credits.correct')).toBeUndefined()
        act(() => root.unmount())
        container.remove()
    })

    it('stays hidden when there is nothing to show or do', async () => {
        const { container, root } = await render(createElement(InvoiceCreditsCard, {
            invoice: { ...paid, status: 'draft', paid_chf: '0.00' }, canManage: true, onChanged: vi.fn(),
        }))
        expect(container.querySelector('section')).toBeNull()
        act(() => root.unmount())
        container.remove()
    })

    it('issues a partial credit through the dialog, with a reason and a capped amount', async () => {
        correctInvoice.mockResolvedValue({ invoice: { ...paid, credits: [credit] }, credit })
        const onChanged = vi.fn()
        const { container, root } = await render(createElement(InvoiceCreditsCard, { invoice: paid, canManage: true, onChanged }))
        await act(async () => { byText(container, 'pages.invoiceDetail.credits.correct')?.click() })
        const form = document.querySelector('form') as HTMLFormElement
        expect(form).toBeTruthy()
        // A reversal is the default and needs only a reason.
        expect(form.querySelector('input[type="number"]')).toBeNull()
        const radios = Array.from(form.querySelectorAll('input[type="radio"]')) as HTMLInputElement[]
        await act(async () => { radios[1].click() })
        const amount = form.querySelector('input[type="number"]') as HTMLInputElement
        expect(amount.max).toBe('100.00')
        expect((form.querySelector('button[type="submit"]') as HTMLButtonElement).disabled).toBe(true)
        const setValue = (el: HTMLInputElement | HTMLTextAreaElement, value: string) => {
            const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype
            Object.getOwnPropertyDescriptor(proto, 'value')?.set?.call(el, value)
            el.dispatchEvent(new Event('input', { bubbles: true }))
        }
        await act(async () => {
            setValue(amount, '10')
            setValue(form.querySelector('textarea') as HTMLTextAreaElement, ' Overcharged ')
        })
        await act(async () => { form.requestSubmit() })
        await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
        expect(correctInvoice).toHaveBeenCalledWith('i1', { kind: 'adjustment', reason: 'Overcharged', amount_chf: '10.00' })
        expect(onChanged).toHaveBeenCalled()
        act(() => root.unmount())
        container.remove()
    })
})

describe('InvoicePaymentsCard with credits', () => {
    const payment = {
        id: 'pay1', invoice: 'i1', amount_chf: '100.00', paid_on: '2026-03-01', note: '',
        source: 'manual' as const, created_by_name: 'Olga', created_at: '2026-03-01T08:00:00Z',
    }

    it('offers removing a payment only while no credit note exists', async () => {
        const open = await render(createElement(InvoicePaymentsCard, {
            invoice: { ...paid, payments: [payment] }, canManage: true, onChanged: vi.fn(),
        }))
        expect(open.container.querySelector('button[aria-label="pages.invoiceDetail.payments.remove"]')).toBeTruthy()
        act(() => open.root.unmount())
        open.container.remove()

        const credited = await render(createElement(InvoicePaymentsCard, {
            invoice: { ...paid, payments: [payment], credits: [credit] }, canManage: true, onChanged: vi.fn(),
        }))
        expect(credited.container.querySelector('button[aria-label="pages.invoiceDetail.payments.remove"]')).toBeNull()
        act(() => credited.root.unmount())
        credited.container.remove()
    })
})
