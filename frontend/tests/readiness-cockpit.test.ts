import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { act } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { MantineProvider } from '@mantine/core'

vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (k: string) => k }),
}))

const mockAuth = vi.fn()
const mockManagedZev = vi.fn()
const mockFetchInvoices = vi.fn()
const mockOpenInvoicePdf = vi.fn()
const mockFetchReadiness = vi.fn()
const mockFetchAttention = vi.fn()

vi.mock('../src/lib/auth', () => ({ useAuth: () => mockAuth() }))

vi.mock('../src/lib/appSettings', () => ({
    useAppSettings: () => ({ settings: {} }),
    formatShortDate: (d: string) => d,
}))

vi.mock('../src/lib/managedZev', () => ({ useManagedZev: () => mockManagedZev() }))

vi.mock('../src/lib/api/invoices', () => ({
    fetchInvoices: (...args: unknown[]) => mockFetchInvoices(...args),
    openInvoicePdf: (...args: unknown[]) => mockOpenInvoicePdf(...args),
}))

vi.mock('../src/lib/api/metering', () => ({
    fetchHourlyProfile: vi.fn(() => Promise.resolve({ hourly_profile: null })),
    fetchMeteringDashboardSummary: vi.fn(() => Promise.resolve(null)),
}))

vi.mock('../src/lib/api/readiness', () => ({
    fetchReadiness: (...args: unknown[]) => mockFetchReadiness(...args),
    fetchReadinessList: vi.fn(),
    fetchAttention: (...args: unknown[]) => mockFetchAttention(...args),
}))

import { BillingCockpit } from '../src/components/BillingCockpit'
import { MyInvoicesPage } from '../src/pages/MyInvoicesPage'
import type { AttentionItem } from '../src/types/api'

function render(node: ReturnType<typeof createElement>, withMantine = false) {
    const container = document.createElement('div')
    document.body.appendChild(container)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const root = createRoot(container)
    act(() => {
        const inner = withMantine
            ? createElement(MantineProvider, null, node)
            : node
        root.render(
            createElement(
                QueryClientProvider,
                { client },
                createElement(MemoryRouter, null, inner),
            ),
        )
    })
    return {
        container,
        html: () => container.innerHTML,
        text: () => container.textContent ?? '',
        unmount: () => {
            act(() => root.unmount())
            container.remove()
        },
    }
}

const GREEN_READINESS = {
    zev_id: '1',
    period: { start: '2026-08-01', end: '2026-08-31', interval: 'monthly' },
    steps: [
        { key: 'metering', status: 'ok', count: 0 },
        { key: 'assignments', status: 'ok', count: 0 },
        { key: 'tariffs', status: 'ok', count: 0 },
        { key: 'generation_conflicts', status: 'ok', count: 0 },
        { key: 'generated', status: 'todo', count: 0, detail: 'Invoices have not been generated for this period', link: '/billing/invoices' },
        { key: 'approved', status: 'todo', count: 0 },
        { key: 'sent', status: 'todo', count: 0 },
        { key: 'paid', status: 'done', count: 0 },
    ],
    next_action: 'generate',
}

const CONFLICT_READINESS = {
    zev_id: '1',
    period: { start: '2026-01-01', end: '2026-03-31', interval: 'quarterly' },
    steps: [
        { key: 'metering', status: 'ok', count: 0 },
        { key: 'assignments', status: 'ok', count: 0 },
        { key: 'tariffs', status: 'ok', count: 0 },
        {
            key: 'generation_conflicts', status: 'warn', count: 1,
            detail_data: {
                conflict_count: 1,
                conflicts: [{
                    participant_id: 'p1', participant_name: 'Anna Aar',
                    invoices: [{
                        id: 'inv-9', number: 'T-00009', status: 'paid',
                        start: '2026-01-01', end: '2026-01-31',
                    }],
                }],
                more_conflicts: 0,
            },
            link: '/billing/invoices?period_start=2026-01-01&period_end=2026-03-31',
        },
        { key: 'generated', status: 'done', count: 0, total: 1 },
        { key: 'approved', status: 'done', count: 0, total: 0 },
        { key: 'sent', status: 'done', count: 0, total: 0 },
        { key: 'paid', status: 'done', count: 0, total: 0 },
    ],
    next_action: 'review_generation_conflicts',
}

describe('BillingCockpit (phase 2 readiness stepper)', () => {
    it.each(['loading', 'error', 'setup', 'awaiting'] as const)(
        'keeps cross-period alerts visible during %s readiness', (state) => {
            const page = render(createElement(BillingCockpit, {
                readinessQuery: {
                    isLoading: state === 'loading', isError: state === 'error',
                    data: state === 'setup' || state === 'awaiting' ? {
                        zev_id: '1', period: null, steps: [], next_action: 'none',
                        ...(state === 'setup' ? { setup: {
                            participants: 1, metering_points: 0, tariffs: 0, settings_complete: false,
                        } } : { awaiting_first_period: true }),
                    } : undefined,
                },
                attentionQuery: { isLoading: false, isError: false, data: [{
                    type: 'invoice_overdue', id: 'invoice_overdue:1', invoice_id: '1',
                    invoice_number: 'INV-1', due_date: '2026-08-01', period: null,
                    link: '/billing/invoices/1', label: 'Fallback',
                }] },
            }), true)
            expect(page.container.querySelector('.cockpit-alert-link')?.getAttribute('href'))
                .toBe('/billing/invoices/1')
            page.unmount()
        },
    )

    it('reports an attention failure independently of successful readiness', () => {
        const page = render(createElement(BillingCockpit, {
            readinessQuery: { isLoading: false, isError: false, data: GREEN_READINESS },
            attentionQuery: { isLoading: false, isError: true },
        }))
        expect(page.container.querySelector('[role="status"]')?.textContent)
            .toBe('pages.dashboard.attention.failed')
        page.unmount()
    })

    it('renders the resolved cockpit period and the eight steps', () => {
        const page = render(
            createElement(BillingCockpit, {
                readinessQuery: { isLoading: false, isError: false, data: GREEN_READINESS },
            }),
        )
        expect(page.text()).toContain('2026-08-01')
        expect(page.text()).toContain('2026-08-31')
        for (const key of ['metering', 'assignments', 'tariffs', 'generated', 'generation_conflicts', 'approved', 'sent', 'paid']) {
            expect(page.html()).toContain('data-status=')
            expect(page.text()).toContain(`pages.dashboard.cockpit.stepLabels.${key}`)
        }        expect(page.text()).toContain('pages.dashboard.cockpit.nextActionLabels.generate')
        expect(page.text()).toContain('pages.dashboard.cockpit.nextUp')
        page.unmount()
    })

    it('renders the generation conflict with its destination link', () => {
        const page = render(
            createElement(BillingCockpit, {
                readinessQuery: { isLoading: false, isError: false, data: CONFLICT_READINESS },
            }),
        )
        expect(page.text()).toContain('pages.dashboard.cockpit.stepLabels.generation_conflicts')
        expect(page.text()).toContain('pages.dashboard.cockpit.stepDetails.conflictsWarn')
        expect(page.text()).toContain('pages.dashboard.cockpit.nextActionLabels.review_generation_conflicts')
        const links = [...page.container.querySelectorAll('.cockpit-step-link')]
            .map((link) => link.getAttribute('href'))
        expect(links).toContain('/billing/invoices?period_start=2026-01-01&period_end=2026-03-31')
        page.unmount()
    })

    it('keeps setup and billing-settings guidance beside period work', () => {
        const page = render(
            createElement(BillingCockpit, {
                readinessQuery: {
                    isLoading: false,
                    isError: false,
                    data: {
                        ...GREEN_READINESS,
                        setup: {
                            participants: 1, metering_points: 1, tariffs: 1,
                            settings_complete: true, complete: false,
                            reason: 'no_billable_assignment',
                            assignment_link: '/metering-points',
                            billing_settings_complete: false,
                            billing_settings_link: '/zev-settings',
                        },
                    },
                },
            }),
        )
        const warnings = page.container.querySelector('.cockpit-setup-warnings')
        expect(warnings?.textContent).toContain('pages.dashboard.cockpit.setupIncomplete')
        expect(warnings?.textContent).toContain('pages.dashboard.cockpit.setupIban')
        const hrefs = [...(warnings?.querySelectorAll('a') ?? [])].map((a) => a.getAttribute('href'))
        expect(hrefs).toContain('/metering-points')
        expect(hrefs).toContain('/zev-settings')
        page.unmount()
    })

    it('shows setup guidance while awaiting the first period', () => {
        const page = render(
            createElement(BillingCockpit, {
                readinessQuery: {
                    isLoading: false,
                    isError: false,
                    data: {
                        zev_id: '1', period: null, steps: [], next_action: 'none',
                        awaiting_first_period: true,
                        setup: {
                            participants: 1, metering_points: 1, tariffs: 1,
                            settings_complete: false, complete: false,
                            reason: 'no_billable_assignment',
                            assignment_link: '/metering-points',
                            billing_settings_complete: false,
                            billing_settings_link: '/zev-settings',
                        },
                    },
                },
            }),
        )
        expect(page.text()).toContain('pages.dashboard.cockpit.awaitingFirstPeriod')
        const warnings = page.container.querySelector('.cockpit-setup-warnings')
        expect(warnings?.textContent).toContain('pages.dashboard.cockpit.setupIncomplete')
        expect(warnings?.textContent).toContain('pages.dashboard.cockpit.setupIban')
        page.unmount()
    })

    it('exposes open-step links only for warn/todo steps', () => {
        const page = render(
            createElement(BillingCockpit, {
                readinessQuery: { isLoading: false, isError: false, data: GREEN_READINESS },
            }),
        )
        // generated (todo, has link) renders a link; metering (ok) does not.
        const links = page.container.querySelectorAll('a.cockpit-step-link')
        expect(links.length).toBeGreaterThan(0)
        const stepItems = Array.from(page.container.querySelectorAll('li.cockpit-step'))
        const meteringStep = stepItems.find((li) => li.textContent?.includes('stepLabels.metering'))
        expect(meteringStep?.querySelector('a.cockpit-step-link')).toBeNull()
        page.unmount()
    })

    it('shows the first-run setup checklist when period is null', () => {
        const page = render(
            createElement(BillingCockpit, {
                readinessQuery: {
                    isLoading: false,
                    isError: false,
                    data: {
                        zev_id: '1',
                        period: null,
                        steps: [],
                        next_action: 'none',
                        setup: { participants: 1, metering_points: 0, tariffs: 0, settings_complete: false },
                    },
                },
            }),
        )
        expect(page.text()).toContain('pages.dashboard.cockpit.firstRunTitle')
        expect(page.text()).toContain('pages.dashboard.cockpit.setupParticipants')
        expect(page.text()).toContain('pages.dashboard.cockpit.setupMeteringPoints')
        expect(page.text()).toContain('pages.dashboard.cockpit.setupTariffs')
        page.unmount()
    })

    it('renders the failure state without throwing', () => {
        const page = render(
            createElement(BillingCockpit, {
                readinessQuery: { isLoading: false, isError: true, data: undefined },
            }),
        )
        expect(page.text()).toContain('pages.dashboard.cockpit.failed')
        page.unmount()
    })
})

describe('BillingCockpit cross-period alerts (merged attention card)', () => {
    const alerts: AttentionItem[] = [
        {
            id: 'email_failed:2',
            type: 'email_failed',
            label: 'RE-0001 — email to x@example.com failed',
            invoice_id: '2',
            invoice_number: 'RE-0001',
            recipient: 'x@example.com',
            period: { start: '2026-08-01', end: '2026-08-31' },
            link: '/billing/invoices?period_start=2026-08-01&period_end=2026-08-31',
        },
        {
            id: 'invoice_overdue:3',
            type: 'invoice_overdue',
            label: 'RE-0002 overdue since 2026-08-01',
            invoice_id: '3',
            invoice_number: 'RE-0002',
            due_date: '2026-08-01',
            period: null,
            link: '/billing/invoices?period_start=2026-07-01&period_end=2026-07-31',
        },
        {
            id: 'participant_validity:9',
            type: 'participant_validity',
            label: 'Anna ended 2026-01-01 but still holds meter assignments',
            participant_id: '9',
            participant_name: 'Anna',
            valid_to: '2026-01-01',
            expired: true,
            period: null,
            link: '/participants?focus=9&field=valid_to',
        },
    ]

    it('renders no alert section when attention is empty or not loaded', () => {
        const page = render(
            createElement(BillingCockpit, {
                readinessQuery: { isLoading: false, isError: false, data: GREEN_READINESS },
            }),
        )
        expect(page.container.querySelector('.cockpit-alerts')).toBeNull()
        page.unmount()
    })

    it('localizes each alert type from structured fields inside the cockpit card', () => {
        const page = render(
            createElement(BillingCockpit, {
                readinessQuery: { isLoading: false, isError: false, data: GREEN_READINESS },
                attentionQuery: { isLoading: false, isError: false, data: alerts },
            }),
        )
        expect(page.container.querySelector('.cockpit-alerts')).not.toBeNull()
        expect(page.text()).toContain('pages.dashboard.attention.text.emailFailed')
        expect(page.text()).toContain('pages.dashboard.attention.text.invoiceOverdue')
        expect(page.text()).toContain('pages.dashboard.attention.text.participantExpired')
        expect(page.text()).toContain('pages.dashboard.attention.labels.email_failed')
        // The English backend fallback must never be rendered.
        expect(page.text()).not.toContain('RE-0001 — email to x@example.com failed')
        expect(page.text()).not.toContain('Anna ended 2026-01-01 but still holds meter assignments')
        // Alerts link to the page that resolves the item.
        expect(
            page.container.querySelector('a[href="/participants?focus=9&field=valid_to"]'),
        ).not.toBeNull()
        page.unmount()
    })
})

describe('MyInvoicesPage (participant own invoices)', () => {
    beforeEach(() => {
        vi.clearAllMocks()
        mockAuth.mockReturnValue({
            user: { id: 5, role: 'participant', username: 'p@example.com' },
        })
    })

    it('lists own invoices with detail links and PDF buttons', async () => {
        mockFetchInvoices.mockResolvedValue([
            {
                id: '7',
                invoice_number: 'RE-2026-001',
                period_start: '2026-08-01',
                period_end: '2026-08-31',
                total_chf: '42.00',
                status: 'sent',
                pdf_url: 'http://x/pdf',
            },
        ])
        const page = render(createElement(MyInvoicesPage), true)
        // Let the react-query observer update land (needs timer ticks, not
        // just a microtask flush).
        await act(async () => {
            await new Promise((resolve) => setTimeout(resolve, 0))
            await new Promise((resolve) => setTimeout(resolve, 0))
        })
        expect(page.text()).toContain('RE-2026-001')
        expect(page.container.querySelector('a[href="/billing/invoices/7"]')).not.toBeNull()
        // Fetch is unscoped: backend narrows participants to their own rows.
        expect(mockFetchInvoices).toHaveBeenCalledWith(undefined)
        page.unmount()
    })

    it('still lists invoices that have no PDF yet, with the PDF action hidden', async () => {
        mockFetchInvoices.mockResolvedValue([
            { id: '8', invoice_number: 'RE-2026-002', status: 'draft', pdf_url: null, total_chf: '1', period_start: '2026-08-01', period_end: '2026-08-31' },
        ])
        const page = render(createElement(MyInvoicesPage), true)
        await act(async () => {
            await new Promise((resolve) => setTimeout(resolve, 0))
            await new Promise((resolve) => setTimeout(resolve, 0))
        })
        // List membership never depends on PDF availability.
        expect(page.text()).toContain('RE-2026-002')
        expect(page.text()).toContain('invoice.status.draft')
        expect(page.container.querySelector('a[href="/billing/invoices/8"]')).not.toBeNull()
        expect(page.text()).not.toContain('pages.myInvoices.empty.title')
        // But the PDF button is conditional on a stored document.
        expect(page.text()).not.toContain('pages.myInvoices.openPdf')
        expect(mockOpenInvoicePdf).not.toHaveBeenCalled()
        page.unmount()
    })

    it('shows the empty state only when the backend returns no invoices', async () => {
        mockFetchInvoices.mockResolvedValue([])
        const page = render(createElement(MyInvoicesPage), true)
        await act(async () => {
            await new Promise((resolve) => setTimeout(resolve, 0))
            await new Promise((resolve) => setTimeout(resolve, 0))
        })
        expect(page.text()).toContain('pages.myInvoices.empty.title')
        page.unmount()
    })

    it('names the issuing community per row for multi-membership participants', async () => {
        mockAuth.mockReturnValue({
            user: { id: 5, role: 'participant', username: 'p@example.com', zev_count: 2 },
        })
        mockFetchInvoices.mockResolvedValue([
            {
                id: '9',
                invoice_number: 'RE-2026-009',
                period_start: '2026-08-01',
                period_end: '2026-08-31',
                total_chf: '42.00',
                status: 'sent',
                pdf_url: null,
                zev_name: 'Second ZEV',
            },
        ])
        const page = render(createElement(MyInvoicesPage), true)
        await act(async () => {
            await new Promise((resolve) => setTimeout(resolve, 0))
            await new Promise((resolve) => setTimeout(resolve, 0))
        })
        expect(page.text()).toContain('Second ZEV')
        expect(page.text()).toContain('pages.myInvoices.col.community')
        page.unmount()
    })
})
