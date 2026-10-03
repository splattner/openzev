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
const mockFetchInvoices = vi.fn()
const mockOpenInvoicePdf = vi.fn()

vi.mock('../src/lib/auth', () => ({ useAuth: () => mockAuth() }))

vi.mock('../src/lib/appSettings', () => ({
    useAppSettings: () => ({ settings: {} }),
    formatShortDate: (d: string) => d,
}))

vi.mock('../src/lib/api/invoices', () => ({
    fetchInvoices: (...args: unknown[]) => mockFetchInvoices(...args),
    openInvoicePdf: (...args: unknown[]) => mockOpenInvoicePdf(...args),
}))

import { SetupGuidance } from '../src/features/overview/SetupGuidance'
import { MyInvoicesPage } from '../src/pages/MyInvoicesPage'

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

describe('SetupGuidance (manager start page)', () => {
    it('renders the loading skeleton', () => {
        const page = render(createElement(SetupGuidance, {
            readinessQuery: { isLoading: true, isError: false },
        }), true)
        expect(page.container.querySelector('.skeleton-block')).not.toBeNull()
        page.unmount()
    })

    it('keeps setup and billing-settings guidance beside period work', () => {
        const page = render(
            createElement(SetupGuidance, {
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
        const warnings = page.container.querySelector('.setup-guidance-warnings')
        expect(warnings?.textContent).toContain('pages.dashboard.cockpit.setupIncomplete')
        expect(warnings?.textContent).toContain('pages.dashboard.cockpit.setupIban')
        const hrefs = [...(warnings?.querySelectorAll('a') ?? [])].map((a) => a.getAttribute('href'))
        expect(hrefs).toContain('/metering-points')
        expect(hrefs).toContain('/zev-settings')
        page.unmount()
    })

    it('warns when the issuer\'s address would leave invoices without a QR bill', () => {
        const page = render(
            createElement(SetupGuidance, {
                readinessQuery: {
                    isLoading: false,
                    isError: false,
                    data: {
                        ...GREEN_READINESS,
                        setup: {
                            participants: 1, metering_points: 1, tariffs: 1,
                            settings_complete: true, complete: true, reason: null, assignment_link: null,
                            billing_settings_complete: true, billing_settings_link: null,
                            issuer_complete: false, issuer_missing: 'address', issuer_link: '/zev-settings/people',
                        },
                    },
                },
            }),
        )
        const warnings = page.container.querySelector('.setup-guidance-warnings')
        expect(warnings?.textContent).toContain('pages.dashboard.cockpit.setupIssuerAddress')
        expect(warnings?.textContent).not.toContain('pages.dashboard.cockpit.setupIban')
        expect(warnings?.querySelector('a')?.getAttribute('href')).toBe('/zev-settings/people')
        page.unmount()
    })

    it('shows setup guidance while awaiting the first period', () => {
        const page = render(
            createElement(SetupGuidance, {
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
        const warnings = page.container.querySelector('.setup-guidance-warnings')
        expect(warnings?.textContent).toContain('pages.dashboard.cockpit.setupIncomplete')
        expect(warnings?.textContent).toContain('pages.dashboard.cockpit.setupIban')
        page.unmount()
    })

    it('shows the first-run setup checklist when period is null', () => {
        const page = render(
            createElement(SetupGuidance, {
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
        expect(page.container.querySelector('a[href="/zev-settings/billing"]')?.closest('li')?.getAttribute('data-complete')).toBe('false')
        page.unmount()
    })

    it('shows the waiting message when setup is complete but no period has ended', () => {
        const page = render(createElement(SetupGuidance, {
            readinessQuery: { isLoading: false, isError: false, data: {
                zev_id: '1', period: null, setup: null, steps: [], next_action: 'none', awaiting_first_period: true,
            } },
        }))
        expect(page.text()).toContain('pages.dashboard.cockpit.awaitingFirstPeriod')
        expect(page.container.querySelector('.setup-guidance-list')).toBeNull()
        page.unmount()
    })

    it('renders the failure state without throwing', () => {
        const page = render(
            createElement(SetupGuidance, {
                readinessQuery: { isLoading: false, isError: true, data: undefined },
            }),
        )
        expect(page.text()).toContain('pages.dashboard.cockpit.failed')
        page.unmount()
    })

    it('renders no setup guidance for a fully configured period', () => {
        const page = render(createElement(SetupGuidance, {
            readinessQuery: {
                isLoading: false,
                isError: false,
                data: {
                    ...GREEN_READINESS,
                    setup: {
                        participants: 1, metering_points: 1, tariffs: 1,
                        settings_complete: true, complete: true,
                        billing_settings_complete: true,
                        assignment_link: '/metering/points',
                        billing_settings_link: '/zev-settings/billing',
                    },
                },
            },
        }))
        expect(page.container.childElementCount).toBe(0)
        page.unmount()
    })
})

describe('MyInvoicesPage (participant own invoices)', () => {
    beforeEach(() => {
        vi.clearAllMocks()
        mockAuth.mockReturnValue({
            user: { id: 5, role: 'user', username: 'p@example.com' },
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
            user: {
                id: 5, role: 'user', username: 'p@example.com',
                memberships: ['First ZEV', 'Second ZEV'].map((name, index) => ({
                    zev: `z${index}`, zev_name: name, zev_disabled: false, access: null, participants: [],
                })),
            },
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
