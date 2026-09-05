import { describe, it, expect, vi } from 'vitest'
import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { act } from 'react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { MantineProvider } from '@mantine/core'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AppRoutes } from '../src/components/AppRoutes'

vi.mock('react-i18next', () => ({
    useTranslation: () => ({
        t: (k: string) => k,
        i18n: { language: 'en', changeLanguage: vi.fn() },
    }),
}))

vi.mock('../src/lib/auth', () => ({
    useAuth: () => ({
        isAuthenticated: true,
        isLoading: false,
        isImpersonating: false,
        impersonator: null,
        user: {
            id: 9,
            username: 'owner@example.com',
            email: 'owner@example.com',
            first_name: '',
            last_name: '',
            role: 'zev_owner',
            must_change_password: false,
        },
    }),
}))

vi.mock('../src/lib/managedZev', () => ({
    ManagedZevProvider: (props: { children: unknown }) => props.children,
    useManagedZev: () => ({
        managedZevs: [{ id: 'z1', name: 'Z1' }],
        selectedZevId: 'z1',
        selectedZev: { id: 'z1', name: 'Z1', billing_interval: 'monthly' },
        isSelectable: false,
        isLoading: false,
        setSelectedZevId: vi.fn(),
    }),
}))

vi.mock('../src/lib/appSettings', () => ({
    useAppSettings: () => ({ settings: {} }),
    formatShortDate: (d: string) => d,
}))

vi.mock('../src/lib/api/zev', () => ({
    fetchZevs: () => Promise.resolve([{ id: 'z1', name: 'Z1' }]),
    fetchMeteringPoints: () => Promise.resolve([{
        id: 'mp1',
        zev: 'z1',
        meter_id: 'CH-TEST-1',
        meter_type: 'consumption',
        is_active: true,
        reading_count: 1,
        assignment_count: 1,
        first_reading_at: '2026-01-01T00:00:00Z',
        last_reading_at: '2026-01-31T00:00:00Z',
    }]),
}))

vi.mock('../src/lib/api/metering', () => ({
    fetchChartData: () => Promise.resolve([]),
    fetchMeteringDataQualityStatus: () => Promise.resolve({
        date_from: '2026-01-01',
        date_to: '2026-01-31',
        metering_points: [{
            id: 'mp1',
            meter_id: 'CH-TEST-1',
            participant_name: 'Test Participant',
            severity: 'red',
            data_completeness: 0,
            days_with_data: 0,
            total_days: 31,
            gaps: [],
            unassigned_days: 0,
            unassigned_readings: 0,
            assignment_overlap: false,
        }],
    }),
}))

vi.mock('../src/lib/toast', () => ({
    useToast: () => ({ pushToast: vi.fn() }),
}))

vi.mock('../src/lib/api/auth', () => ({
    fetchUsers: () => Promise.resolve([]),
}))

function LocationProbe() {
    const location = useLocation()
    return createElement('output', { 'data-testid': 'location' }, `${location.pathname}${location.search}`)
}

async function renderChart(initialEntry = '/metering/chart') {
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)
    await act(async () => {
        root.render(
            createElement(
                MemoryRouter,
                { initialEntries: [initialEntry] },
                createElement(
                    MantineProvider,
                    null,
                    createElement(
                        QueryClientProvider,
                        { client: new QueryClient({ defaultOptions: { queries: { retry: false } } }) },
                        createElement(AppRoutes),
                    ),
                ),
                createElement(LocationProbe),
            ),
        )
    })
    await act(async () => {
        await new Promise((r) => setTimeout(r, 0))
    })
    // The real page arrives behind lazy(); wait for the period control
    // (generous budget — the full suite runs files in parallel).
    // NOTE: kept as an explicit poll loop — vi.waitFor() without act() does
    // not flush the lazy() state updates, so it returns before content lands.
    for (let i = 0; i < 100 && !container.querySelector('.period-selector-range')?.textContent; i += 1) {
        await act(async () => {
            await new Promise((r) => setTimeout(r, 50))
        })
    }
    return {
        container,
        unmount: () => {
            act(() => root.unmount())
            container.remove()
        },
    }
}

function buttonByText(container: HTMLElement, text: string) {
    const buttons = Array.from(container.querySelectorAll('button'))
    const found = buttons.find((b) => b.textContent === text)
    if (!found) throw new Error(`button "${text}" not found`)
    return found
}

describe('metering tab state', () => {
    it('keeps the selected period and resolution across tab switches (no remount)', async () => {
        const { container, unmount } = await renderChart()
        const range = () => container.querySelector('.period-selector-range')?.textContent ?? ''

        const initial = range()
        expect(initial).not.toBe('')

        await act(async () => {
            buttonByText(container, 'pages.invoices.prevPeriod').click()
        })
        const historical = range()
        expect(historical).not.toBe(initial)
        const historicalLocation = container.querySelector('[data-testid="location"]')?.textContent ?? ''
        expect(historicalLocation).toContain('period_start=')
        expect(historicalLocation).toContain('period_end=')
        expect(historicalLocation).not.toContain('from=')
        expect(historicalLocation).not.toContain('to=')

        // Switch resolution away from the default (React doesn't reflect value
        // to the attribute — identify the select by its options).
        const resolution = Array.from(container.querySelectorAll('select')).find((s) =>
            Array.from(s.options).some((o) => o.value === 'hour'),
        ) as HTMLSelectElement | undefined
        expect(resolution?.value).toBe('day')
        await act(async () => {
            resolution!.value = 'month'
            resolution!.dispatchEvent(new Event('change', { bubbles: true }))
        })

        await act(async () => {
            buttonByText(container, 'nav.meteringDataQuality').click()
        })
        expect(range()).toBe(historical)

        await act(async () => {
            buttonByText(container, 'nav.meteringData').click()
        })
        expect(range()).toBe(historical)
        const back = Array.from(container.querySelectorAll('select')).find((s) =>
            Array.from(s.options).some((o) => o.value === 'hour'),
        ) as HTMLSelectElement | undefined
        expect(back?.value).toBe('month')
        unmount()
        // Real page behind lazy() plus full AppRoutes render: needs headroom.
    }, 30000)

    it('routes a Data Quality meter link to its chart without losing the period', async () => {
        const { container, unmount } = await renderChart(
            '/metering/quality?from=2026-01-01&to=2026-01-31&quality_severity=red',
        )

        const range = container.querySelector('.period-selector-range')?.textContent ?? ''
        expect(range).toContain('2026-01-01')
        expect(range).toContain('2026-01-31')

        for (let i = 0; i < 100 && !Array.from(container.querySelectorAll('button')).some((button) => button.textContent === 'CH-TEST-1'); i += 1) {
            await act(async () => {
                await new Promise((resolve) => setTimeout(resolve, 50))
            })
        }

        await act(async () => {
            buttonByText(container, 'CH-TEST-1').click()
        })

        expect(container.querySelector('[data-testid="location"]')?.textContent).toBe(
            '/metering/chart?from=2026-01-01&to=2026-01-31&quality_severity=red&metering_point=mp1',
        )
        unmount()
    }, 30000)
})
