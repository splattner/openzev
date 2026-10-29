import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { DynamicPriceHistoryPanel } from '../src/features/tariffs/DynamicPriceHistoryModal'
import type { DynamicPriceHistory, DynamicTariffSource } from '../src/types/api'

const api = vi.hoisted(() => ({ fetchDynamicPriceHistory: vi.fn() }))

vi.mock('react-i18next', () => ({
    useTranslation: () => ({
        t: (key: string, options?: Record<string, unknown>) => (options ? `${key} ${JSON.stringify(options)}` : key),
    }),
}))
vi.mock('../src/lib/api/tariffs', () => ({ fetchDynamicPriceHistory: api.fetchDynamicPriceHistory }))
vi.mock('../src/lib/appSettings', async importOriginal => ({
    ...await importOriginal<typeof import('../src/lib/appSettings')>(),
    useAppSettings: () => ({ settings: { date_format_short: 'dd.MM.yyyy', date_time_format: 'dd.MM.yyyy HH:mm' } }),
}))
// The date pickers and the chart are not what is under test; jsdom has no
// layout for the chart anyway.
vi.mock('../src/components/CivilDateInput', () => ({ CivilDateInput: () => null }))
vi.mock('recharts', () => {
    const empty = () => null
    return {
        CartesianGrid: empty, Line: empty, LineChart: empty, ReferenceArea: empty,
        ResponsiveContainer: empty, Tooltip: empty, XAxis: empty, YAxis: empty,
    }
})

const SOURCE = { id: 's1', api_version: 'v1_0_5', covers_from: null, covers_to: null } as unknown as DynamicTariffSource

function history(count: number): DynamicPriceHistory {
    const points = Array.from({ length: count }, (_, index) => {
        const start = Date.UTC(2026, 8, 1) + index * 900_000
        return {
            valid_from: new Date(start).toISOString(),
            valid_to: new Date(start + 900_000).toISOString(),
            price_chf_per_kwh: '0.12345',
        }
    })
    return {
        points, gaps: [],
        stats: {
            point_count: count, minimum_chf_per_kwh: null, maximum_chf_per_kwh: null,
            average_chf_per_kwh: null, negative_count: 0, gap_count: 0,
        },
    }
}

let container: HTMLElement
let root: Root

async function flush() {
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)) })
}

async function mount(count: number, compact: boolean) {
    api.fetchDynamicPriceHistory.mockResolvedValue(history(count))
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    await act(async () => {
        root.render(createElement(QueryClientProvider, { client }, createElement(DynamicPriceHistoryPanel, { source: SOURCE, compact })))
    })
    await flush()
    if (compact) {
        // The compact panel keeps the table behind a lazy disclosure.
        const details = container.querySelector('details')!
        await act(async () => {
            details.open = true
            details.dispatchEvent(new Event('toggle'))
        })
    }
}

const bodyRows = () => container.querySelectorAll('tbody tr')
const button = (label: string) => container.querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`)!

beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
})

afterEach(() => {
    act(() => root.unmount())
    container.remove()
    api.fetchDynamicPriceHistory.mockReset()
})

describe('the fetched-price table in the tariff pane', () => {
    it('shows 12 rows at a time and pages through the range', async () => {
        await mount(30, true)
        expect(bodyRows()).toHaveLength(12)
        expect(container.querySelector('.data-table-footer')?.textContent).toContain('"from":1,"to":12,"total":30')

        await act(async () => { button('common.pagination.next').click() })
        expect(bodyRows()).toHaveLength(12)
        expect(container.querySelector('.data-table-footer')?.textContent).toContain('"from":13,"to":24,"total":30')

        await act(async () => { button('common.pagination.next').click() })
        expect(bodyRows()).toHaveLength(6)
        expect(button('common.pagination.next').disabled).toBe(true)

        await act(async () => { button('common.pagination.previous').click() })
        expect(bodyRows()).toHaveLength(12)
        // One validity cell per row, the day named once.
        expect(bodyRows()[0].querySelector('td')?.textContent).toMatch(/^\d\d\.\d\d\.\d{4} \d\d:\d\d – \d\d:\d\d$/)
        // Paging never refetches: the date range is untouched.
        expect(api.fetchDynamicPriceHistory).toHaveBeenCalledTimes(1)
    })

    it('shows no pager when the range fits one page', async () => {
        await mount(12, true)
        expect(bodyRows()).toHaveLength(12)
        expect(container.querySelector('.data-table-footer')).toBeNull()
    })

    it('keeps the empty-range message', async () => {
        await mount(0, true)
        expect(container.querySelector('tbody')?.textContent).toContain('pages.dynamicSources.history.empty')
        expect(container.querySelector('.data-table-footer')).toBeNull()
    })

    it('leaves the admin dialog table on its long pages', async () => {
        await mount(30, false)
        expect(bodyRows()).toHaveLength(30)
        expect(container.querySelector('.data-table-footer')).toBeNull()
    })
})
