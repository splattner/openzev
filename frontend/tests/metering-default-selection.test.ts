import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { MantineProvider } from '@mantine/core'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MeteringChartPage, ALL_METERING_POINTS_VALUE } from '../src/pages/MeteringChartPage'
import type { MeteringPointDataQuality } from '../src/types/api'

type Relation = 'admin' | 'manager' | 'viewer' | 'participant'

const state = vi.hoisted(() => ({
    relation: 'manager' as Relation,
    zevId: 'z1',
    meters: [] as Array<{ id: string; zev: string; meter_id: string }>,
    chartCalls: [] as Array<Record<string, unknown>>,
    meterCalls: [] as Array<string | undefined>,
    assignmentCalls: [] as string[],
    /** Holds the meter list back until released (default: answered at once). */
    meterGate: undefined as Promise<void> | undefined,
    meterListFails: false,
    qualityPoints: [] as MeteringPointDataQuality[],
}))

vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (k: string) => k, i18n: { language: 'en', changeLanguage: vi.fn() } }),
}))

vi.mock('../src/lib/auth', () => ({
    useAuth: () => ({
        user: {
            id: 9, role: state.relation === 'admin' ? 'admin' : 'user', preferred_zev: null,
            memberships: [{ zev: 'z1', zev_name: 'Z1' }, { zev: 'z2', zev_name: 'Z2' }],
        },
    }),
}))

vi.mock('../src/lib/managedZev', () => {
    const value = () => {
        const manages = state.relation !== 'participant'
        const name = state.zevId === 'z1' ? 'Z1' : 'Z2'
        return {
            managedZevs: manages ? [{ id: state.zevId, name }] : [],
            entries: [{ id: state.zevId, name, relation: state.relation }],
            selectedZevId: state.zevId,
            selectedZev: manages ? { id: state.zevId, name, billing_interval: 'monthly', start_date: '2024-01-01' } : null,
            relation: state.relation,
            isSelectable: false,
            isLoading: false,
            isFetching: false,
            isError: false,
            refetch: vi.fn(),
            setSelectedZevId: vi.fn(),
        }
    }
    return { useManagedZev: value, useOptionalManagedZev: value }
})

vi.mock('../src/lib/appSettings', () => ({
    useAppSettings: () => ({ settings: {} }),
    formatShortDate: (d: string) => d,
}))

vi.mock('../src/lib/api/zev', () => ({
    fetchZevs: () => Promise.resolve([{ id: 'z1', name: 'Z1' }, { id: 'z2', name: 'Z2' }]),
    fetchMeteringPoints: async (zevId?: string) => {
        state.meterCalls.push(zevId)
        await state.meterGate
        if (state.meterListFails) throw new Error('meter list unavailable')
        return state.meters.filter((meter) => !zevId || meter.zev === zevId).map((meter) => ({
            ...meter, meter_type: 'consumption', is_active: true, reading_count: 1, assignment_count: 1,
            first_reading_at: null, last_reading_at: null,
        }))
    },
    fetchMeteringPointAssignments: (meteringPoint: string) => {
        state.assignmentCalls.push(meteringPoint)
        return Promise.resolve([])
    },
}))

vi.mock('../src/lib/api/metering', () => ({
    fetchChartData: (params: Record<string, unknown>) => {
        state.chartCalls.push(params)
        return Promise.resolve([])
    },
    fetchMeteringDataQualityStatus: () => Promise.resolve({ date_from: '2026-01-01', date_to: '2026-01-31', metering_points: state.qualityPoints }),
    fetchRawMeteringData: () => Promise.resolve([]),
    fetchRawMeteringDay: () => Promise.resolve([]),
}))

function LocationProbe() {
    const location = useLocation()
    return createElement('output', { 'data-testid': 'location' }, `${location.pathname}${location.search}`)
}

const meter = (id: string, zev = 'z1') => ({ id, zev, meter_id: `CH-${id}` })

const mounted: Array<() => void> = []

/** Releasable gate for the meter list, to observe the states before it answers. */
function holdMeterList() {
    let release!: () => void
    state.meterGate = new Promise<void>((resolve) => { release = resolve })
    return async () => {
        await act(async () => { release() })
    }
}

async function renderChart(path = '/metering/chart', tab: 'chart' | 'quality' = 'chart', { settled = true } = {}) {
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)
    // Registered first, so a failing assertion still unmounts the tree.
    mounted.push(() => { act(() => root.unmount()); container.remove() })
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const render = () => root.render(createElement(MemoryRouter, { initialEntries: [path] },
        createElement(MantineProvider, { theme: { components: { Drawer: { defaultProps: { transitionProps: { duration: 0 } } } } } },
            createElement(QueryClientProvider, { client }, createElement(MeteringChartPage, { tab }))),
        createElement(LocationProbe)))
    // Settled once no query is in flight and the page stopped changing:
    // results can start further queries (meter list → chart → raw table).
    const settle = async () => {
        let previous = ''
        await vi.waitFor(async () => {
            await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
            const current = container.innerHTML
            const stable = current === previous && client.isFetching() === 0
            previous = current
            expect(stable).toBe(true)
        })
    }
    await act(async () => { render() })
    if (settled) await settle()
    const select = () => container.querySelector<HTMLSelectElement>('select')!
    return {
        container,
        client,
        select,
        options: () => Array.from(select().options).map((option) => option.value),
        location: () => container.querySelector('[data-testid="location"]')?.textContent ?? '',
        emptyTitle: () => container.querySelector('.empty-state h3')?.textContent ?? null,
        rerender: async (nextTab = tab) => {
            tab = nextTab
            await act(async () => { render() })
            await settle()
        },
        settle,
        /** Flush pending effects and promise callbacks without waiting for quiescence. */
        flush: () => act(async () => { await new Promise((r) => setTimeout(r, 0)) }),
    }
}

afterEach(() => {
    mounted.splice(0).forEach((unmount) => unmount())
    state.meterGate = undefined
    state.meterListFails = false
    state.relation = 'manager'
    state.zevId = 'z1'
    state.meters = []
    state.chartCalls = []
    state.meterCalls = []
    state.assignmentCalls = []
    state.qualityPoints = []
})

describe('metering gap selection', () => {
    const point: MeteringPointDataQuality = {
        id: 'mp1', meter_id: 'CH-mp1', participant_name: 'Period holder',
        severity: 'yellow', data_completeness: 96.8, days_with_data: 30, total_days: 31,
        gaps: [{ start_date: '2026-10-02', end_date: '2026-10-02', duration_days: 1 }],
        unassigned_days: 0, unassigned_readings: 0, assignment_overlap: false,
    }
    const drawer = () => document.querySelector('[role="dialog"]')

    async function openGaps() {
        state.meters = [meter('mp1'), meter('mp2'), meter('mp3', 'z2')]
        state.qualityPoints = [point]
        const view = await renderChart('/metering/quality?period_start=2026-10-01&period_end=2026-10-31', 'quality')
        await act(async () => { view.container.querySelector<HTMLButtonElement>('tbody button[aria-haspopup="dialog"]')!.click() })
        expect(drawer()?.textContent).toContain('CH-mp1')
        return view
    }

    it.each(['removed point', 'filled gaps'])('stays closed after a refetch restores a %s', async (change) => {
        const view = await openGaps()
        state.qualityPoints = change === 'removed point' ? [] : [{ ...point, gaps: [] }]
        await act(async () => { await view.client.invalidateQueries({ queryKey: ['metering', 'quality-status'] }) })
        await view.settle()
        expect(drawer()).toBeNull()
        state.qualityPoints = [point]
        await act(async () => { await view.client.invalidateQueries({ queryKey: ['metering', 'quality-status'] }) })
        await view.settle()
        expect(view.container.querySelector('tbody button[aria-haspopup="dialog"]')).not.toBeNull()
        expect(drawer()).toBeNull()
    })

    it('uses updated quality data while the selected point still has gaps', async () => {
        const view = await openGaps()
        state.qualityPoints = [{ ...point, participant_name: 'Updated holder' }]
        await act(async () => { await view.client.invalidateQueries({ queryKey: ['metering', 'quality-status'] }) })
        await view.settle()
        expect(drawer()?.textContent).toContain('Updated holder')
        expect(drawer()?.textContent).not.toContain('Period holder')
    })

    it.each(['tab', 'community', 'period', 'meter', 'severity'])('stays closed when the %s context changes and returns', async (context) => {
        const view = await openGaps()
        const change = async (restore: boolean) => {
            if (context === 'tab') return view.rerender(restore ? 'quality' : 'chart')
            if (context === 'community') {
                state.zevId = restore ? 'z1' : 'z2'
                return view.rerender()
            }
            await act(async () => {
                if (context === 'period') {
                    view.container.querySelector<HTMLButtonElement>(`button[title="pages.invoices.${restore ? 'nextPeriod' : 'prevPeriod'}"]`)!.click()
                } else if (context === 'meter') {
                    view.select().value = restore ? '' : 'mp2'
                    view.select().dispatchEvent(new Event('change', { bubbles: true }))
                } else {
                    Array.from(view.container.querySelectorAll<HTMLButtonElement>('button[aria-pressed]'))
                        .find(button => button.textContent?.includes('meteringDataQuality.severityYellow'))!.click()
                }
            })
            await view.settle()
        }
        await change(false)
        expect(drawer()).toBeNull()
        await change(true)
        expect(drawer()).toBeNull()
    })
})

describe('metering chart default selection', () => {
    it.each<Relation>(['admin', 'manager', 'viewer'])('opens the whole-community total for a %s without touching the URL', async (relation) => {
        state.relation = relation
        state.meters = [meter('mp1'), meter('mp2')]
        const view = await renderChart()
        expect(state.chartCalls.length).toBeGreaterThan(0)
        expect(state.chartCalls.every((call) => call.zevId === 'z1' && !call.meteringPoint)).toBe(true)
        expect(view.select().value).toBe(ALL_METERING_POINTS_VALUE)
        // The total is always a choice: no empty placeholder.
        expect(view.options()).toEqual([ALL_METERING_POINTS_VALUE, 'mp1', 'mp2'])
        expect(view.location()).toBe('/metering/chart')
        expect(view.container.textContent).toContain('pages.meteringData.rawTable.unavailableForZevTotal')
    })

    it('opens a participant\'s only meter, with its raw readings', async () => {
        state.relation = 'participant'
        state.meters = [meter('mp1'), meter('other', 'z2')]
        const view = await renderChart()
        expect(state.meterCalls).toContain('z1')
        expect(state.chartCalls.length).toBeGreaterThan(0)
        expect(state.chartCalls.every((call) => call.meteringPoint === 'mp1')).toBe(true)
        expect(view.select().value).toBe('mp1')
        expect(view.options()).toEqual(['mp1'])
        expect(view.location()).toBe('/metering/chart')
        expect(view.container.textContent).not.toContain('pages.meteringData.rawTable.unavailableForZevTotal')
        // Assignments are management data: a participant never requests them (403).
        expect(state.assignmentCalls).toEqual([])
    })

    it('lets a participant with several meters choose one', async () => {
        state.relation = 'participant'
        state.meters = [meter('mp1'), meter('mp2')]
        const view = await renderChart()
        expect(state.chartCalls).toEqual([])
        expect(view.options()).toEqual(['', 'mp1', 'mp2'])
        expect(view.emptyTitle()).toBe('pages.meteringData.noPointSelectedTitle')
    })

    it('explains when a participant has no meters in the community', async () => {
        state.relation = 'participant'
        const view = await renderChart()
        expect(state.chartCalls).toEqual([])
        expect(view.emptyTitle()).toBe('pages.meteringData.noOwnMetersTitle')
        expect(view.container.querySelector('.empty-state a')).toBeNull()
    })

    it('points a management reader of an empty community to the metering points', async () => {
        state.relation = 'viewer'
        const view = await renderChart()
        expect(view.emptyTitle()).toBe('pages.meteringData.noMetersTitle')
        expect(view.container.querySelector('.empty-state a')?.getAttribute('href')).toBe('/metering/points')
        expect(view.container.querySelector('.recharts-wrapper, .stat-grid')).toBeNull()
    })

    it('keeps an explicit meter over the default', async () => {
        state.meters = [meter('mp1'), meter('mp2')]
        const view = await renderChart('/metering/chart?metering_point=mp2')
        expect(state.assignmentCalls).toContain('mp2')
        expect(state.chartCalls.length).toBeGreaterThan(0)
        expect(state.chartCalls.every((call) => call.meteringPoint === 'mp2')).toBe(true)
        expect(view.select().value).toBe('mp2')
    })

    it('leaves the Data Quality tab on all meters', async () => {
        state.meters = [meter('mp1'), meter('mp2')]
        const view = await renderChart('/metering/quality', 'quality')
        expect(view.select().value).toBe('')
        expect(state.chartCalls).toEqual([])
    })

    it('recomputes the default when the relation changes with the community', async () => {
        state.meters = [meter('mp1'), meter('mp9', 'z2')]
        const view = await renderChart()
        expect(state.chartCalls.at(-1)).toMatchObject({ zevId: 'z1' })
        state.chartCalls = []
        state.relation = 'participant'
        state.zevId = 'z2'
        await view.rerender()
        expect(state.chartCalls.length).toBeGreaterThan(0)
        expect(state.chartCalls.every((call) => call.meteringPoint === 'mp9' && !call.zevId)).toBe(true)
        expect(view.location()).toBe('/metering/chart')
        // Two memberships, participant view: the header still names the selected community.
        expect(view.container.querySelector('.eyebrow')?.textContent).toBe('Z2')
    })
    describe('loading order', () => {
        it('requests the total at once but shows it only after a nonempty meter list', async () => {
            state.meters = [meter('mp1')]
            const release = holdMeterList()
            const view = await renderChart('/metering/chart', 'chart', { settled: false })
            await vi.waitFor(async () => {
                await view.flush()
                expect(state.chartCalls).toContainEqual(expect.objectContaining({ zevId: 'z1' }))
            })
            expect(view.container.querySelector('.skeleton-block')).not.toBeNull()
            expect(view.container.querySelector('.stat-grid')).toBeNull()
            await release()
            await view.settle()
            expect(view.container.querySelector('.stat-grid')).not.toBeNull()
        })

        it('never shows a chart for a community whose meter list comes back empty', async () => {
            const release = holdMeterList()
            const view = await renderChart('/metering/chart', 'chart', { settled: false })
            await vi.waitFor(async () => {
                await view.flush()
                expect(state.chartCalls.length).toBeGreaterThan(0)
            })
            expect(view.container.querySelector('.stat-grid')).toBeNull()
            await release()
            await view.settle()
            expect(view.emptyTitle()).toBe('pages.meteringData.noMetersTitle')
            expect(view.container.querySelector('.stat-grid')).toBeNull()
        })

        it('waits for a participant\'s meter list without a chart request or a premature prompt', async () => {
            state.relation = 'participant'
            state.meters = [meter('mp1'), meter('mp2')]
            const release = holdMeterList()
            const view = await renderChart('/metering/chart', 'chart', { settled: false })
            await vi.waitFor(async () => {
                await view.flush()
                expect(state.meterCalls).toContain('z1')
            })
            expect(state.chartCalls).toEqual([])
            expect(view.emptyTitle()).toBeNull()
            await release()
            await view.settle()
            expect(state.chartCalls).toEqual([])
            expect(view.emptyTitle()).toBe('pages.meteringData.noPointSelectedTitle')
        })

        it('shows the total with a retry when the meter list fails', async () => {
            state.meterListFails = true
            const view = await renderChart()
            expect(view.container.querySelector('.stat-grid')).not.toBeNull()
            const notice = view.container.querySelector('.error-banner')
            expect(notice).not.toBeNull()
            expect(Array.from(notice!.querySelectorAll('button')).map((button) => button.textContent)).toContain('common.retry')
        })
    })
})
