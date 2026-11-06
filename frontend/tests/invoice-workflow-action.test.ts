import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { InvoiceWorkflowAction } from '../src/features/invoices/InvoiceWorkflowAction'
import type { EmailLog, Invoice } from '../src/types/api'

const api = vi.hoisted(() => ({ approve: vi.fn(), send: vi.fn(), toast: vi.fn() }))
vi.mock('../src/lib/api/invoices', () => ({ approveInvoice: api.approve, sendInvoiceEmail: api.send, openInvoicePdf: vi.fn() }))
vi.mock('../src/lib/auth', () => ({ useAuth: () => ({ user: { id: 1 } }) }))
vi.mock('../src/lib/toast', () => ({ useToast: () => ({ pushToast: api.toast }) }))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
const base: Invoice = {
    id: 'invoice-1', invoice_number: 'INV-1', zev: 'invoice-community', zev_name: 'Community', participant: 'participant-1', participant_name: 'Anna',
    period_start: '2026-07-01', period_end: '2026-09-30', status: 'draft', total_chf: '100.00', email_logs: [],
}
function emailLog(id: string, status: EmailLog['status']): EmailLog {
    return { id, invoice: base.id, recipient: 'anna@example.com', subject: 'Invoice', status, created_at: '2026-11-05T12:00:00Z' }
}
const cleanups: Array<() => void> = []
beforeEach(() => vi.resetAllMocks())
afterEach(() => { cleanups.splice(0).forEach(cleanup => cleanup()); vi.restoreAllMocks() })
async function flush() { await act(async () => { await new Promise(resolve => setTimeout(resolve, 10)) }) }
async function mount(invoice = base, canManage = true) {
    const container = document.createElement('div')
    document.body.append(container)
    const root = createRoot(container)
    const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
    let current = invoice, writable = canManage
    const changed = vi.fn((updated: Invoice) => { current = updated; render() })
    function render() {
        root.render(createElement(QueryClientProvider, { client }, createElement(InvoiceWorkflowAction, { invoice: current, canManage: writable, onChanged: changed })))
    }
    await act(async () => render())
    await flush()
    cleanups.push(() => { act(() => root.unmount()); client.clear(); container.remove() })
    return { container, client, changed, show: async (next: Invoice, allowed = true) => { current = next; writable = allowed; await act(async () => render()); await flush() } }
}
async function click(container: ParentNode) { await act(async () => container.querySelector('button')!.click()); await flush() }

describe('invoice detail workflow action', () => {
    it('approves the invoice and replaces the one button with Send email', async () => {
        api.approve.mockResolvedValue({ ...base, status: 'approved' })
        const { container, changed } = await mount()
        expect(container.querySelectorAll('button')).toHaveLength(1)
        expect(container.textContent).toContain('pages.invoices.approve')
        await click(container)
        expect(api.approve).toHaveBeenCalledExactlyOnceWith(base.id)
        expect(changed).toHaveBeenCalledWith(expect.objectContaining({ status: 'approved' }))
        expect(container.querySelectorAll('button')).toHaveLength(1)
        expect(container.textContent).toContain('pages.invoices.sendEmail')
    })

    it('polls the actual detail after queuing email and allows retry after failed delivery', async () => {
        api.send.mockResolvedValue({ queued: true })
        const intervals = vi.spyOn(window, 'setInterval')
        const approved = { ...base, status: 'approved' }
        const { container, client, changed, show } = await mount(approved)
        const invalidate = vi.spyOn(client, 'invalidateQueries')
        await click(container)
        expect(api.send).toHaveBeenCalledExactlyOnceWith(base.id)
        expect(changed).not.toHaveBeenCalled()
        expect(invalidate).toHaveBeenCalledWith({ queryKey: ['invoices', 'list'] })
        expect(invalidate).toHaveBeenCalledWith({ queryKey: ['invoices', 'period-overview'] })
        expect(invalidate).toHaveBeenCalledWith({ queryKey: ['invoices', 'mine'] })
        expect(container.querySelector('button')?.disabled).toBe(true)
        expect(container.textContent).toContain('pages.invoices.sending')
        invalidate.mockClear()
        const poll = intervals.mock.calls.find(call => call[1] === 2500)?.[0]
        expect(typeof poll).toBe('function')
        act(() => { if (typeof poll === 'function') poll() })
        expect(invalidate).toHaveBeenCalledWith({ queryKey: ['invoices', 'detail', base.id] })
        await show({ ...approved, last_email_status: 'failed', email_logs: [emailLog('new-log', 'failed')] })
        expect(container.textContent).toContain('pages.invoices.issues.delivery')
        expect(container.querySelector('button')?.disabled).toBe(false)
        expect(container.textContent).toContain('pages.invoices.sendEmail')
    })

    it('observes an email already pending when detail opens and unlocks after its failure', async () => {
        const pending: Invoice = { ...base, status: 'approved', last_email_status: 'pending', email_logs: [emailLog('pending-log', 'pending')] }
        const { container, show } = await mount(pending)
        expect(container.querySelector('button')?.disabled).toBe(true)
        await show({ ...pending, last_email_status: 'failed', email_logs: [{ ...pending.email_logs![0], status: 'failed' }] })
        expect(container.querySelector('button')?.disabled).toBe(false)
        expect(api.send).not.toHaveBeenCalled()
    })

    it('offers a read-only status refresh after the delivery deadline without resending', async () => {
        const timeouts = vi.spyOn(window, 'setTimeout')
        const pending: Invoice = { ...base, status: 'approved', last_email_status: 'pending', email_logs: [emailLog('pending-log', 'pending')] }
        const { container, client, show } = await mount(pending)
        const expire = timeouts.mock.calls.find(call => Number(call[1]) > 89000)?.[0]
        expect(typeof expire).toBe('function')
        act(() => { if (typeof expire === 'function') expire() })
        await flush()
        expect(container.textContent).toContain('pages.invoices.messages.emailPollingTimeout')
        expect(api.toast).not.toHaveBeenCalled()
        expect(container.textContent).not.toContain('pages.invoices.sending')
        const invalidate = vi.spyOn(client, 'invalidateQueries')
        await click(container.querySelector('[role="status"]')!)
        expect(invalidate).toHaveBeenCalledWith({ queryKey: ['invoices', 'detail', base.id] })
        expect(api.send).not.toHaveBeenCalled()
        await show({ ...pending, last_email_status: 'failed', email_logs: [emailLog('pending-log', 'failed')] })
        expect(container.querySelector('button')?.disabled).toBe(false)
    })

    it.each([
        ['read-only', base, false], ['correction review', { ...base, needs_data_review: true }, true],
        ['sent', { ...base, status: 'sent' }, true], ['paid', { ...base, status: 'paid' }, true], ['cancelled', { ...base, status: 'cancelled' }, true],
    ] as const)('omits an ordinary action for %s', async (_state, invoice, allowed) => {
        const { container } = await mount(invoice, allowed)
        expect(container.querySelector('button')).toBeNull()
        expect(api.approve).not.toHaveBeenCalled()
        expect(api.send).not.toHaveBeenCalled()
    })

    it('keeps approval recoverable after a request error', async () => {
        api.approve.mockRejectedValue(new Error('Offline'))
        const { container, changed } = await mount()
        await click(container)
        expect(changed).not.toHaveBeenCalled()
        expect(container.querySelector('button')?.disabled).toBe(false)
        expect(api.toast).toHaveBeenCalledWith(expect.any(String), 'error')
    })

    it('does not apply late feedback after invoice write permission is lost', async () => {
        let resolve!: (invoice: Invoice) => void
        api.approve.mockReturnValue(new Promise(done => { resolve = done }))
        const { container, changed, show } = await mount()
        await click(container)
        await show(base, false)
        await act(async () => resolve({ ...base, status: 'approved' }))
        await flush()
        expect(changed).not.toHaveBeenCalled()
        expect(api.toast).not.toHaveBeenCalled()
    })
})
