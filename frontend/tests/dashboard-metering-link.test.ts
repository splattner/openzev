import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { act } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { MantineProvider } from '@mantine/core'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { readPeriodFromSearchParams } from '../src/pages/MeteringChartPage'

vi.mock('react-i18next', () => ({
    useTranslation: () => ({
        t: (k: string) => k,
        i18n: { language: 'en', changeLanguage: vi.fn() },
    }),
}))

vi.mock('../src/lib/auth', () => ({
    useAuth: () => ({
        user: { role: 'zev_owner', zev_count: 1, zev_name: 'Z1' },
    }),
}))

vi.mock('../src/lib/managedZev', () => ({
    useManagedZev: () => ({
        managedZevs: [{ id: 'z1', name: 'Z1' }],
        selectedZevId: 'z1',
        selectedZev: { id: 'z1', name: 'Z1', billing_interval: 'monthly' },
        isLoading: false,
    }),
}))

vi.mock('../src/lib/appSettings', () => ({
    useAppSettings: () => ({ settings: {} }),
    formatShortDate: (d: string) => d,
}))

vi.mock('../src/lib/api/metering', () => ({
    fetchMeteringDashboardSummary: () =>
        Promise.resolve({
            role: 'zev_owner',
            bucket: 'day',
            zev_totals: { produced_kwh: 10, consumed_kwh: 8, imported_kwh: 2, exported_kwh: 4 },
            timeline: [],
            participant_stats: [],
            selected_participant_name: null,
        }),
    fetchHourlyProfile: () => Promise.resolve({ hourly_profile: null }),
}))

vi.mock('../src/lib/api/invoices', () => ({
    fetchInvoices: () => Promise.resolve([]),
    openInvoicePdf: vi.fn(),
}))

import { DashboardPage } from '../src/pages/DashboardPage'

const cleanups: Array<() => void> = []
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))

async function renderManagerDashboard() {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)
    await act(async () => {
        root.render(
            createElement(
                MantineProvider,
                null,
                createElement(
                    QueryClientProvider,
                    { client },
                    createElement(MemoryRouter, null, createElement(DashboardPage)),
                ),
            ),
        )
    })
    await act(async () => {
        await new Promise((r) => setTimeout(r, 0))
    })
    cleanups.push(() => {
        act(() => root.unmount())
        container.remove()
    })
    return container
}

describe('manager energy balance metering handoff', () => {
    it('links to the metering chart with the current period and no participant filter', async () => {
        const container = await renderManagerDashboard()
        const link = container.querySelector('a[href^="/metering/chart"]') as HTMLAnchorElement | null
        expect(link).not.toBeNull()
        const url = new URL(link!.getAttribute('href')!, 'http://localhost')
        expect(readPeriodFromSearchParams(url.searchParams)).not.toBeNull()
        expect(url.searchParams.get('participant_id')).toBeNull()
    })

    it('no longer renders the removed per-participant table', async () => {
        const container = await renderManagerDashboard()
        expect(container.textContent).not.toContain('pages.dashboard.col.participant')
        expect(container.textContent).toContain('pages.dashboard.perParticipantMigrated')
    })
})
