import { describe, expect, it, vi } from 'vitest'
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MantineProvider } from '@mantine/core'
import type { Credit, Invoice } from '../src/types/api'
import {
    amountDueChf,
    appliedCreditChf,
    canAdjustInvoice,
    canCorrectInvoice,
    canRefundCredit,
    hasCreditApplied,
} from '../src/features/invoices/invoiceCredits'
import { InvoiceCreditBreakdown, InvoiceTotal } from '../src/components/InvoicePresentation'
import { InvoiceCreditsCard } from '../src/features/invoices/InvoiceCreditsCard'
import { InvoicePaymentsCard } from '../src/features/invoices/InvoicePaymentsCard'
import { ToastProvider } from '../src/lib/toast'

vi.mock('react-i18next', () => ({
    useTranslation: () => ({
        t: (k: string, options?: Record<string, unknown>) => (options ? `${k} ${JSON.stringify(options)}` : k),
        i18n: { language: 'en', changeLanguage: vi.fn() },
    }),
}))

vi.mock('../src/lib/appSettings', () => ({
    useAppSettings: () => ({ settings: {}, isLoading: false }),
    formatShortDate: (v: string | null | undefined) => v ?? '',
    toDayJsDateFormat: () => 'DD.MM.YYYY',
}))

const refundCredit = vi.fn()
const correctInvoice = vi.fn()
vi.mock('../src/lib/api/invoices', () => ({
    refundCredit: (...args: unknown[]) => refundCredit(...args),
    correctInvoice: (...args: unknown[]) => correctInvoice(...args),
    openCreditPdf: vi.fn(),
    openInvoicePdf: vi.fn(),
    recordPayment: vi.fn(),
    markInvoicePaid: vi.fn(),
    deletePayment: vi.fn(),
}))

const application = { id: 'a1', credit: 'c0', credit_number: 'CN-00000', amount_chf: '30.00', released_at: null }

// 100.00 total, 30.00 settled by credit, 70.00 paid in cash.
const partlyCredit: Invoice = {
    id: 'i1', invoice_number: 'INV-1', zev: 'z1', zev_name: 'Community A', participant: 'p1', participant_name: 'Anna',
    period_start: '2026-02-01', period_end: '2026-02-28', status: 'paid', total_chf: '100.00',
    credit_applied_chf: '30.00', amount_due_chf: '70.00', paid_chf: '70.00', outstanding_chf: '0.00',
    payments: [], credits: [], credit_applications: [application],
}

// Settled by credit alone: paid without any payment.
const creditOnly: Invoice = {
    ...partlyCredit, total_chf: '30.00', credit_applied_chf: '30.00', amount_due_chf: '0.00', paid_chf: '0.00',
}

const openCredit: Credit = {
    id: 'c1', credit_number: 'CN-00001', zev: 'z1', participant: 'p1', participant_name: 'Anna', kind: 'adjustment',
    source_invoice: 'i0', source_invoice_number: 'INV-0', reason: 'Overcharged', amount_chf: '50.00',
    vat_mode: 'not_registered', vat_rate: '0.0000', vat_chf: '0.00', embedded_vat_chf: null, remaining_chf: '20.00',
    refunded_chf: '0.00', refunded_on: null, refund_note: '', status: 'open', pdf_url: 'http://x/pdf/', pdf_status: 'ready',
    applications: [{ id: 'ap1', invoice: 'i1', invoice_number: 'INV-1', amount_chf: '30.00', released_at: null }],
    created_by_name: 'Olga', created_at: '2026-03-02T08:00:00Z',
}

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

describe('amount due', () => {
    it('is shown only when credit reduced the total of a live invoice', () => {
        expect(amountDueChf(partlyCredit)).toBe(70)
        expect(amountDueChf({ total_chf: '40.00' })).toBe(40)
        expect(hasCreditApplied(partlyCredit)).toBe(true)
        expect(hasCreditApplied({ ...partlyCredit, credit_applied_chf: '0.00', amount_due_chf: '100.00' })).toBe(false)
        expect(hasCreditApplied({ ...partlyCredit, status: 'cancelled' })).toBe(false)
    })

    it('renders beneath the total, with each credit note applied in the breakdown', async () => {
        const total = await render(createElement(InvoiceTotal, { invoice: partlyCredit }))
        expect(total.container.textContent).toContain('invoice.amountDue')
        expect(total.container.textContent).toContain('70.00')
        act(() => total.root.unmount())
        total.container.remove()

        const plain = await render(createElement(InvoiceTotal, {
            invoice: { ...partlyCredit, credit_applied_chf: '0.00', amount_due_chf: '100.00' },
        }))
        expect(plain.container.textContent).not.toContain('invoice.amountDue')
        act(() => plain.root.unmount())
        plain.container.remove()

        const breakdown = await render(createElement(InvoiceCreditBreakdown, { invoice: partlyCredit }))
        expect(breakdown.container.textContent).toContain('CN-00000')
        expect(breakdown.container.textContent).toContain('invoice.amountDue')
        act(() => breakdown.root.unmount())
        breakdown.container.remove()
    })
})

describe('correcting an invoice that used credit', () => {
    it('counts only the applications that were not released', () => {
        expect(appliedCreditChf(partlyCredit)).toBe(30)
        expect(appliedCreditChf({ credit_applications: [{ ...application, released_at: '2026-03-01T00:00:00Z' }] })).toBe(0)
    })

    it('allows a reversal with applications only, but not a partial credit', () => {
        expect(canCorrectInvoice(creditOnly, true)).toBe(true)
        expect(canAdjustInvoice(creditOnly, true)).toBe(false)
        expect(canCorrectInvoice(partlyCredit, true)).toBe(true)
        expect(canAdjustInvoice(partlyCredit, true)).toBe(true)
        expect(canCorrectInvoice(creditOnly, false)).toBe(false)
    })

    it('has nothing to reverse once the credit was released and the cash credited', () => {
        const released = { ...creditOnly, credit_applications: [{ ...application, released_at: '2026-03-01T00:00:00Z' }] }
        expect(canCorrectInvoice(released, true)).toBe(false)
    })

    it('offers no partial credit in the dialog for a credit-only invoice, and explains the release', async () => {
        const { container, root } = await render(createElement(InvoiceCreditsCard, {
            invoice: creditOnly, canManage: true, onChanged: vi.fn(),
        }))
        await act(async () => { byText(container, 'pages.invoiceDetail.credits.correct')?.click() })
        const form = document.querySelector('form') as HTMLFormElement
        const radios = Array.from(form.querySelectorAll('input[type="radio"]')) as HTMLInputElement[]
        expect(radios[0].disabled).toBe(false)
        expect(radios[1].disabled).toBe(true)
        expect(form.textContent).toContain('pages.invoiceDetail.credits.reversalNoCashHint')
        expect(form.textContent).toContain('pages.invoiceDetail.credits.releasesCredit')
        expect(form.textContent).toContain('30.00')
        act(() => root.unmount())
        container.remove()
    })
})

describe('InvoicePaymentsCard with credit applied', () => {
    it('offers recording a payment only while an amount is due', async () => {
        const sent: Invoice = { ...partlyCredit, status: 'sent', paid_chf: '0.00', outstanding_chf: '70.00' }
        const due = await render(createElement(InvoicePaymentsCard, { invoice: sent, canManage: true, onChanged: vi.fn() }))
        expect(byText(due.container, 'pages.invoiceDetail.payments.record')).toBeTruthy()
        act(() => due.root.unmount())
        due.container.remove()

        const covered: Invoice = { ...creditOnly, status: 'sent', paid_chf: '0.00', outstanding_chf: '0.00' }
        const none = await render(createElement(InvoicePaymentsCard, { invoice: covered, canManage: true, onChanged: vi.fn() }))
        expect(byText(none.container, 'pages.invoiceDetail.payments.record')).toBeUndefined()
        expect(byText(none.container, 'pages.invoices.markPaid')).toBeTruthy()
        act(() => none.root.unmount())
        none.container.remove()
    })
})

describe('refunding a credit note', () => {
    it('is offered to managers on an open credit only', () => {
        expect(canRefundCredit(openCredit, true)).toBe(true)
        expect(canRefundCredit(openCredit, false)).toBe(false)
        expect(canRefundCredit({ ...openCredit, status: 'used' }, true)).toBe(false)
        expect(canRefundCredit({ ...openCredit, status: 'refunded' }, true)).toBe(false)
    })

    it('shows the remaining amount, the status and where the credit was applied', async () => {
        const { container, root } = await render(createElement(InvoiceCreditsCard, {
            invoice: { ...partlyCredit, credits: [openCredit] }, canManage: false, onChanged: vi.fn(),
        }))
        expect(container.textContent).toContain('20.00')
        expect(container.textContent).toContain('pages.invoiceDetail.credits.status.open')
        expect(container.textContent).toContain('INV-1')
        expect(container.querySelector('button[aria-label^="pages.invoiceDetail.credits.refund"]')).toBeNull()
        act(() => root.unmount())
        container.remove()
    })

    it('books the remainder through the dialog, with today as the default date and a trimmed note', async () => {
        refundCredit.mockResolvedValue({ ...openCredit, status: 'refunded', remaining_chf: '0.00' })
        const onCreditChanged = vi.fn()
        const { container, root } = await render(createElement(InvoiceCreditsCard, {
            invoice: { ...partlyCredit, credits: [openCredit] }, canManage: true, onChanged: vi.fn(), onCreditChanged,
        }))
        await act(async () => {
            (container.querySelector('button[aria-label^="pages.invoiceDetail.credits.refund"]') as HTMLButtonElement).click()
        })
        const form = document.querySelector('form') as HTMLFormElement
        expect(form).toBeTruthy()
        expect(form.textContent).toContain('20.00')
        const note = form.querySelector('input[type="text"]') as HTMLInputElement
        await act(async () => {
            Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set?.call(note, ' IBAN CH93 ')
            note.dispatchEvent(new Event('input', { bubbles: true }))
        })
        await act(async () => { form.requestSubmit() })
        await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
        expect(refundCredit).toHaveBeenCalledWith('c1', { refunded_on: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/), note: 'IBAN CH93' })
        expect(onCreditChanged).toHaveBeenCalled()
        act(() => root.unmount())
        container.remove()
    })
})
