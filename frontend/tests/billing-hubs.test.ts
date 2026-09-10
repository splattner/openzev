import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, useNavigate, useLocation } from 'react-router-dom'

const api = vi.hoisted(() => ({
    list: vi.fn(),
    retry: vi.fn(),
    overview: vi.fn(),
    readiness: vi.fn(),
    history: vi.fn(),
}))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('../src/lib/managedZev', () => ({ useManagedZev: () => ({
    selectedZevId: 'z1', selectedZev: { id: 'z1', name: 'ZEV', start_date: '2025-01-01', billing_interval: 'monthly' },
}) }))
vi.mock('../src/lib/auth', () => ({ useAuth: () => ({ user: { role: 'zev_owner' } }) }))
vi.mock('../src/lib/toast', () => ({ useToast: () => ({ pushToast: vi.fn() }) }))
vi.mock('../src/lib/appSettings', () => ({
    useAppSettings: () => ({ settings: {} }),
    formatShortDate: (d: string) => d,
    formatDateTime: (d: string) => d,
}))
vi.mock('../src/lib/api/invoices', () => ({
    fetchInvoices: api.list,
    retryFailedEmail: api.retry,
    fetchInvoicePeriodOverview: api.overview,
    fetchEmailLogs: api.history,
}))
vi.mock('../src/lib/api/readiness', () => ({ fetchReadinessList: api.readiness }))
vi.mock('../src/components/PageSkeleton', () => ({ PageSkeleton: () => null }))
vi.mock('../src/features/invoices/useInvoiceActions', () => ({ useInvoiceActions: () => ({ stats: {}, deleteMutation: {} }) }))
vi.mock('../src/features/invoices/InvoiceDeleteModal', () => ({ InvoiceDeleteModal: () => null }))
vi.mock('../src/features/invoices/InvoicesEmptyState', () => ({ InvoicesEmptyState: () => null }))
vi.mock('../src/components/PeriodSelector', () => ({ PeriodSelector: (props: { from: string; to: string; minFrom: string }) =>
    createElement('output', { 'data-floor': props.minFrom }, `${props.from}/${props.to}`),
}))

import { BillingEmailsPage } from '../src/pages/BillingEmailsPage'
import { BillingPeriodsPage } from '../src/pages/BillingPeriodsPage'
import { InvoicesPage } from '../src/pages/InvoicesPage'

const cleanups: (() => void)[] = []
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))
beforeEach(() => {
    vi.clearAllMocks()
    api.overview.mockResolvedValue({ rows: [] })
    api.history.mockResolvedValue([{
        id: 'log-1', invoice: 'failed', recipient: 'anna@example.com', subject: 'Invoice',
        status: 'failed', error_message: 'bounced', created_at: '2026-02-01T12:00:00Z',
    }])
    api.list.mockResolvedValue([
        { id: 'failed', invoice_number: 'FAILED', status: 'approved', last_email_status: 'failed', last_email_log_id: 'log-1' },
        { id: 'sent', invoice_number: 'SENT', status: 'sent', last_email_status: 'sent', last_email_log_id: 'log-2' },
        { id: 'paid', invoice_number: 'PAID', status: 'paid', last_email_status: 'sent', last_email_log_id: 'log-3' },
    ])
})

async function mount(component: typeof BillingEmailsPage | typeof InvoicesPage | typeof BillingPeriodsPage, path = '/billing/emails') {
    const container = document.createElement('div')
    document.body.append(container)
    const root = createRoot(container)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    let navigate: ReturnType<typeof useNavigate>
    function Host() {
        navigate = useNavigate()
        const location = useLocation()
        return createElement('div', { 'data-location': location.search }, createElement(component))
    }
    await act(async () => {
        root.render(createElement(QueryClientProvider, { client },
            createElement(MemoryRouter, { initialEntries: [path] }, createElement(Host))))
    })
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)) })
    cleanups.push(() => { act(() => root.unmount()); client.clear(); container.remove() })
    return { container, client, navigate: async (to: string) => { await act(async () => navigate(to)) } }
}

describe('Billing hub interactions', () => {
    it('distinguishes period status from the next action and links to the blocking workflow', async () => {
        const destination = '/metering/quality?period_start=2025-02-01&period_end=2025-02-28'
        api.readiness.mockResolvedValue([{
            period: { start: '2025-02-01', end: '2025-02-28' }, next_action: 'fix_metering',
            steps: [{ key: 'metering', status: 'warn', link: destination }],
        }])
        const { container } = await mount(BillingPeriodsPage, '/billing/periods')
        expect(api.readiness).toHaveBeenCalledWith('z1')
        expect(container.querySelector('.overview-period-card')?.textContent).toContain('pages.billingPeriods.status.attention')
        expect(container.querySelector('a')?.getAttribute('href')).toBe(destination)
        expect(container.querySelector('a')?.textContent).toBe('pages.dashboard.cockpit.nextActionLabels.fix_metering')
    })

    it('keeps invoice alerts visible when period readiness fails', async () => {
        api.readiness.mockRejectedValue(new Error('Unavailable'))
        const { container } = await mount(() => createElement(BillingPeriodsPage, {
            attentionQuery: { isLoading: false, isError: false, data: [{
                id: 'overdue:1', type: 'invoice_overdue', label: 'API fallback',
                invoice_id: '1', invoice_number: 'INV-1',
                period: { start: '2026-06-01', end: '2026-06-30' },
                link: '/billing/invoices?period_start=2026-06-01&period_end=2026-06-30',
            }] },
        }))
        expect(container.textContent).toContain('pages.billingPeriods.failed')
        expect(container.querySelectorAll('.overview-period-card')).toHaveLength(1)
        expect(container.querySelector('.overview-period-card > a')?.getAttribute('href'))
            .toBe('/billing/invoices?period_start=2026-06-01&period_end=2026-06-30')
        expect(container.textContent).not.toContain('pages.overview.cards.upToDate')
    })

    it('does not declare periods completed when the alert query failed', async () => {
        api.readiness.mockResolvedValue([{
            period: { start: '2026-06-01', end: '2026-06-30', ended: true },
            steps: [], next_action: 'none',
        }])
        const { container } = await mount(() => createElement(BillingPeriodsPage, {
            attentionQuery: { isLoading: false, isError: true },
        }))
        expect(container.textContent).toContain('pages.dashboard.attention.failed')
        expect(container.querySelector('.overview-period-history')).toBeNull()
        expect(container.querySelector('.overview-caught-up')).toBeNull()
    })

    it('shows a quiet caught-up state and collapsed history once both queries succeed', async () => {
        api.readiness.mockResolvedValue([{
            period: { start: '2026-06-01', end: '2026-06-30', ended: true },
            steps: [], next_action: 'none',
        }])
        const { container } = await mount(() => createElement(BillingPeriodsPage, {
            attentionQuery: { isLoading: false, isError: false, data: [] },
        }))
        expect(container.querySelector('.overview-caught-up')).not.toBeNull()
        expect(container.querySelector('details')?.open).toBe(false)
    })

    it('renders one status filter and narrows the email rows', async () => {
        const { container } = await mount(BillingEmailsPage)
        expect(api.list).toHaveBeenCalledWith('z1', { status: 'approved,sent,paid' })
        expect(container.querySelectorAll('select')).toHaveLength(1)
        const select = container.querySelector('select')!
        await act(async () => { select.value = 'failed'; select.dispatchEvent(new Event('change', { bubbles: true })) })
        expect(container.querySelector('tbody')?.textContent).toContain('FAILED')
        expect(container.querySelector('tbody')?.textContent).not.toContain('SENT')
    })

    it('opens the delivery history on the email page, including paid invoices', async () => {
        const { container } = await mount(BillingEmailsPage)
        expect(container.querySelector('tbody')?.textContent).toContain('PAID')
        const historyButton = [...container.querySelectorAll('button')].find((button) =>
            button.textContent?.includes('pages.billingEmails.viewHistory'),
        )
        expect(historyButton).toBeDefined()
        await act(async () => historyButton?.click())
        await act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)) })
        expect(api.history).toHaveBeenCalledWith('failed')
        expect(container.textContent).toContain('pages.invoices.emailLogs.title')
        expect(container.textContent).toContain('anna@example.com')
    })

    it('retries the latest log and disables retry while the request is pending', async () => {
        let resolveRetry!: () => void
        api.retry.mockImplementation(() => new Promise<void>((resolve) => { resolveRetry = resolve }))
        const { container, client } = await mount(BillingEmailsPage)
        const button = [...container.querySelectorAll('button')].find((candidate) =>
            candidate.textContent?.includes('pages.billingEmails.retry'),
        )!
        await act(async () => button.click())
        await act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)) })
        expect(api.retry).toHaveBeenCalledWith('failed', 'log-1')
        expect(button.disabled).toBe(true)
        await act(async () => resolveRetry())
        await act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)) })
        // A queued worker has not created the next log yet: stale failed
        // data must not re-enable Retry and enqueue duplicate deliveries.
        expect([...container.querySelectorAll('button')].some((candidate) =>
            candidate.textContent?.includes('pages.billingEmails.retry'),
        )).toBe(false)
        expect(container.querySelector('tbody')?.textContent).toContain('pages.invoices.emailLogs.status.pending')
        api.list.mockResolvedValue([
            { id: 'failed', invoice_number: 'FAILED', status: 'approved', last_email_status: 'failed', last_email_log_id: 'log-new' },
        ])
        await act(async () => { await client.invalidateQueries({ queryKey: ['invoices'] }) })
        await act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)) })
        const refreshedRetry = [...container.querySelectorAll('button')].find((candidate) =>
            candidate.textContent?.includes('pages.billingEmails.retry'),
        )
        expect(refreshedRetry?.disabled).toBe(false)
    })

    it('updates the invoice period when a deep link changes without remounting', async () => {
        const page = await mount(InvoicesPage, '/billing/invoices?period_start=2025-02-01&period_end=2025-02-28')
        expect(page.container.querySelector('output')?.textContent).toBe('2025-02-01/2025-02-28')
        await page.navigate('/billing/invoices?period_start=2025-03-01&period_end=2025-03-31')
        expect(page.container.querySelector('output')?.textContent).toBe('2025-03-01/2025-03-31')
        expect(page.container.querySelector('output')?.getAttribute('data-floor')).toBe('2025-01-01')
        expect(api.overview).toHaveBeenLastCalledWith({ zev_id: 'z1', period_start: '2025-03-01', period_end: '2025-03-31' })
    })

    it('keeps two periods sharing a start as separate cards with exact-date links', async () => {
        api.readiness.mockResolvedValue([
            {
                period: { start: '2026-01-01', end: '2026-01-31', interval: 'monthly', source: 'invoice' },
                next_action: 'approve', steps: [{ key: 'approved', status: 'todo' }],
            },
            {
                period: { start: '2026-01-01', end: '2026-03-31', interval: 'quarterly', source: 'calendar' },
                next_action: 'review_generation_conflicts',
                steps: [{ key: 'generation_conflicts', status: 'warn' }],
            },
        ])
        const { container } = await mount(BillingPeriodsPage, '/billing/periods')
        const rows = container.querySelectorAll('.overview-period-card')
        expect(rows).toHaveLength(2)
        const hrefs = [...container.querySelectorAll('.overview-period-card a')]
            .map((link) => link.getAttribute('href'))
        expect(hrefs).toContain('/billing/invoices?period_start=2026-01-01&period_end=2026-01-31')
        expect(hrefs).toContain('/billing/invoices?period_start=2026-01-01&period_end=2026-03-31')
        expect(container.textContent).toContain('pages.dashboard.cockpit.stepDetails.conflictsWarn')
    })

    it('shows the running period as collecting data, never as needing attention', async () => {
        api.readiness.mockResolvedValue([{
            period: { start: '2026-09-01', end: '2026-09-30', interval: 'monthly', source: 'calendar', ended: false },
            next_action: 'fix_metering',
            steps: [{ key: 'metering', status: 'warn', count: 1 }],
        }])
        const { container } = await mount(BillingPeriodsPage, '/billing/periods')
        const current = container.querySelector('.billing-current-period')
        expect(current?.textContent).toContain('pages.billingPeriods.status.collecting')
        expect(current?.textContent).not.toContain('pages.billingPeriods.status.attention')
        expect(container.querySelector('tbody')).toBeNull()
    })
})
