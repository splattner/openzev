import { describe, it, expect, vi } from 'vitest'
import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { act } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { MantineProvider } from '@mantine/core'

vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (k: string) => k }),
}))

import { SetupGuidance } from '../src/features/overview/SetupGuidance'

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
            readinessQuery: { refetch: vi.fn(), isLoading: true, isError: false },
        }), true)
        expect(page.container.querySelector('.skeleton-block')).not.toBeNull()
        page.unmount()
    })

    it('keeps setup and billing-settings guidance beside period work', () => {
        const page = render(
            createElement(SetupGuidance, {
                readinessQuery: { refetch: vi.fn(),
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
                readinessQuery: { refetch: vi.fn(),
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
                readinessQuery: { refetch: vi.fn(),
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
        // Each step's link names its progress; the icon is decorative.
        const steps = Array.from(page.container.querySelectorAll('.setup-guidance-list li'))
        expect(steps.map((step) => step.querySelector('a')?.textContent)).toEqual([
            'pages.dashboard.cockpit.setupDone pages.dashboard.cockpit.setupParticipants',
            'pages.dashboard.cockpit.setupTodo pages.dashboard.cockpit.setupMeteringPoints',
            'pages.dashboard.cockpit.setupTodo pages.dashboard.cockpit.setupTariffs',
            'pages.dashboard.cockpit.setupTodo pages.dashboard.cockpit.setupSettings',
        ])
        expect(steps.every((step) => step.querySelector('svg')?.getAttribute('aria-hidden') === 'true')).toBe(true)
        expect(page.text()).not.toMatch(/[✓○]/)
        page.unmount()
    })

    it('shows the waiting message when setup is complete but no period has ended', () => {
        const page = render(createElement(SetupGuidance, {
            readinessQuery: { refetch: vi.fn(), isLoading: false, isError: false, data: {
                zev_id: '1', period: null, setup: null, steps: [], next_action: 'none', awaiting_first_period: true,
            } },
        }))
        expect(page.text()).toContain('pages.dashboard.cockpit.awaitingFirstPeriod')
        expect(page.container.querySelector('.setup-guidance-list')).toBeNull()
        page.unmount()
    })

    it('offers retry for a failed readiness request', () => {
        const refetch = vi.fn()
        const page = render(
            createElement(SetupGuidance, {
                readinessQuery: { refetch, isLoading: false, isError: true, data: undefined },
            }),
        )
        expect(page.text()).toContain('pages.dashboard.cockpit.failed')
        expect(page.container.querySelector('.error-banner')?.getAttribute('role')).toBe('alert')
        act(() => page.container.querySelector<HTMLButtonElement>('button')!.click())
        expect(refetch).toHaveBeenCalledOnce()
        page.unmount()
    })

    it('renders no setup guidance for a fully configured period', () => {
        const page = render(createElement(SetupGuidance, {
            readinessQuery: { refetch: vi.fn(),
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
