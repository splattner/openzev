import { waitForCondition } from './helpers/waitForCondition'
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MantineProvider } from '@mantine/core'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const state = vi.hoisted(() => ({ zevId: '42', userId: 1, toast: vi.fn() }))
vi.mock('../src/lib/auth', () => ({ useAuth: () => ({ user: { id: state.userId, role: 'admin' } }) }))
vi.mock('../src/lib/managedZev', () => {
    const context = { useManagedZev: () => ({
        selectedZevId: state.zevId, selectedZev: { id: state.zevId }, isLoading: false, isError: false,
    }) }
    return { ...context, useOptionalManagedZev: context.useManagedZev }
})
vi.mock('../src/lib/toast', () => ({ useToast: () => ({ pushToast: state.toast }) }))
vi.mock('../src/lib/appSettings', () => ({
    useAppSettings: () => ({ settings: {} }), formatShortDate: (value: string) => value,
    formatDateTime: (value: string) => value,
}))
vi.mock('react-i18next', () => ({ useTranslation: () => ({
    t: (key: string, options?: { number?: string }) => options?.number ? `${key}:${options.number}` : key,
}) }))
vi.mock('../src/lib/api/invoices', () => ({
    fetchInvoices: vi.fn(), fetchEmailLogs: vi.fn(), retryFailedEmail: vi.fn(),
}))

import { BillingEmailsPage } from '../src/pages/BillingEmailsPage'
import { fetchEmailLogs, fetchInvoices, retryFailedEmail } from '../src/lib/api/invoices'
import type { EmailLog, Invoice } from '../src/types/api'

function deferred() {
    let resolve!: (logs: EmailLog[]) => void
    let reject!: (error: Error) => void
    const promise = new Promise<EmailLog[]>((yes, no) => { resolve = yes; reject = no })
    return { promise, resolve, reject }
}

let root: ReturnType<typeof createRoot>
let client: QueryClient
let container: HTMLDivElement

async function render() {
    await act(async () => root.render(createElement(MemoryRouter, null,
        createElement(QueryClientProvider, { client },
            createElement(MantineProvider, null, createElement(BillingEmailsPage))),
    )))
    await waitForCondition(() => container.querySelectorAll('.billing-workflow-table tbody tr').length === 2, 'invoice rows')
}

function historyButtons() {
    return Array.from(container.querySelectorAll<HTMLButtonElement>('.billing-workflow-table button'))
}

function modalTitle() {
    return container.querySelector('h3')?.textContent
}

beforeEach(async () => {
    state.zevId = '42'
    state.userId = 1
    vi.clearAllMocks()
    vi.mocked(fetchInvoices).mockResolvedValue(['A', 'B'].map((name, index) => ({
        id: String(index + 1), zev: '42', invoice_number: name, participant_name: name,
        period_start: '2026-09-01', period_end: '2026-09-30', status: 'sent',
    })) as Invoice[])
    container = document.createElement('div')
    document.body.append(container)
    root = createRoot(container)
    client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    await render()
})

afterEach(() => {
    act(() => root.unmount())
    client.clear()
    container.remove()
})

describe('billing email history request ownership', () => {
    it('keeps the newer history when the older request finishes last', async () => {
        const a = deferred(), b = deferred()
        vi.mocked(fetchEmailLogs).mockImplementation(id => id === '1' ? a.promise : b.promise)
        act(() => { historyButtons()[0].click(); historyButtons()[1].click() })
        await act(async () => { b.resolve([]); await b.promise })
        expect(modalTitle()).toBe('pages.invoices.emailLogs.title:B')
        await act(async () => { a.resolve([]); await a.promise })
        expect(modalTitle()).toBe('pages.invoices.emailLogs.title:B')
    })

    it('does not clear the newer loading state or toast an older failure', async () => {
        const a = deferred(), b = deferred()
        vi.mocked(fetchEmailLogs).mockImplementation(id => id === '1' ? a.promise : b.promise)
        act(() => { historyButtons()[0].click(); historyButtons()[1].click() })
        await act(async () => { a.reject(new Error('Old failure')); await a.promise.catch(() => {}) })
        expect(historyButtons()[1].disabled).toBe(true)
        expect(state.toast).not.toHaveBeenCalled()
        await act(async () => { b.resolve([]); await b.promise })
        expect(modalTitle()).toBe('pages.invoices.emailLogs.title:B')
    })

    it('closing history invalidates a pending request before reopening it', async () => {
        vi.mocked(fetchEmailLogs).mockResolvedValueOnce([])
        act(() => historyButtons()[0].click())
        await act(async () => { await Promise.resolve() })
        const old = deferred(), latest = deferred()
        vi.mocked(fetchEmailLogs).mockReturnValueOnce(old.promise).mockReturnValueOnce(latest.promise)
        act(() => historyButtons()[1].click())
        act(() => Array.from(container.querySelectorAll<HTMLButtonElement>('button'))
            .find(button => button.textContent?.trim() === 'common.close')!.click())
        expect(historyButtons().every(button => !button.disabled)).toBe(true)
        act(() => historyButtons()[0].click())
        await act(async () => { latest.resolve([]); await latest.promise })
        await act(async () => { old.resolve([]); await old.promise })
        expect(modalTitle()).toBe('pages.invoices.emailLogs.title:A')
    })

    it('ignores a failed history request after unmount', async () => {
        const pending = deferred()
        vi.mocked(fetchEmailLogs).mockReturnValue(pending.promise)
        act(() => historyButtons()[0].click())
        act(() => root.render(null))
        await act(async () => { pending.reject(new Error('Late failure')); await pending.promise.catch(() => {}) })
        expect(state.toast).not.toHaveBeenCalled()
        expect(modalTitle()).toBeUndefined()
    })

    for (const changed of ['community', 'account']) {
        for (const loaded of [false, true]) {
            it(`clears ${loaded ? 'open' : 'pending'} history after a ${changed} change`, async () => {
                const a = deferred()
                vi.mocked(fetchEmailLogs).mockReturnValue(a.promise)
                act(() => historyButtons()[0].click())
                if (loaded) {
                    await act(async () => { a.resolve([]); await a.promise })
                    expect(modalTitle()).toBe('pages.invoices.emailLogs.title:A')
                }
                if (changed === 'community') state.zevId = '43'
                else state.userId = 2
                await render()
                await act(async () => { a.resolve([]); await a.promise })
                expect(modalTitle()).toBeUndefined()
                expect(historyButtons().every(button => !button.disabled)).toBe(true)
            })
        }
    }
})

describe('billing email retry ownership', () => {
    for (const change of ['community', 'account']) {
        for (const outcome of ['success', 'failure']) {
            it(`ignores a retry ${outcome} after changing ${change}`, async () => {
                const invoices = vi.mocked(fetchInvoices).mock.results[0].value as Promise<Invoice[]>
                vi.mocked(fetchInvoices).mockResolvedValue((await invoices).map(invoice => ({
                    ...invoice, last_email_status: 'failed', last_email_log_id: `log${invoice.id}`,
                })))
                await act(async () => { await client.invalidateQueries() })
                await waitForCondition(() => !!Array.from(container.querySelectorAll('button')).find(button => button.textContent === 'pages.billingEmails.retry'), 'delivery retry')
                let resolve!: () => void
                let reject!: (error: Error) => void
                const pending = new Promise<void>((yes, no) => { resolve = yes; reject = no })
                vi.mocked(retryFailedEmail).mockImplementation(() => pending.then(() => ({ status: 'queued' })))
                act(() => Array.from(container.querySelectorAll<HTMLButtonElement>('button'))
                    .find(button => button.textContent === 'pages.billingEmails.retry')!.click())
                await waitForCondition(() => vi.mocked(retryFailedEmail).mock.calls.length === 1, 'email retry request')
                expect(retryFailedEmail).toHaveBeenCalledWith('1', 'log1')
                const mutation = client.getMutationCache().getAll().at(-1)!
                if (change === 'community') state.zevId = '43'
                else state.userId = 2
                await render()
                const invalidate = vi.spyOn(client, 'invalidateQueries')
                await act(async () => {
                    if (outcome === 'success') resolve()
                    else reject(new Error('Old retry failed'))
                    await pending.catch(() => {})
                })
                await waitForCondition(() => !['idle', 'pending'].includes(mutation.state.status), 'obsolete retry completion')
                expect(state.toast).not.toHaveBeenCalled()
                expect(invalidate).not.toHaveBeenCalled()
                expect(modalTitle()).toBeUndefined()
            })
        }
    }
})
