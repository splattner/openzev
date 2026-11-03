import { act, createElement } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MyEnergyView } from '../src/features/myEnergy/MyEnergyView'
import { businessDayStartMs, todayBusinessIso } from '../src/lib/dates'
import {
    lastDaysRange,
    ownHistoryFromSeries,
    parseMyEnergyRange,
    shiftIsoDate,
    showMyEnergyEntry,
    todayRows,
} from '../src/lib/myEnergy'
import type { EligibleMeteringPoint, GrossEnergy, LiveCurve, LiveSnapshot, OwnSeries, ProductionForecast } from '../src/types/api'
import { renderWithProviders } from './helpers/render'

vi.mock('react-i18next', () => ({
    useTranslation: () => ({
        t: (key: string, options?: Record<string, unknown>) => (options ? `${key}|${JSON.stringify(options)}` : key),
        i18n: { language: 'en', resolvedLanguage: 'en' },
    }),
}))
vi.mock('../src/lib/appSettings', async (importOriginal) => {
    const actual = await importOriginal<typeof import('../src/lib/appSettings')>()
    return { ...actual, useAppSettings: () => ({ settings: actual.DEFAULT_APP_SETTINGS, isLoading: false }) }
})

const mockAccess = vi.hoisted(() => vi.fn())
vi.mock('../src/lib/communityAccess', () => ({ useCommunityAccess: () => mockAccess() }))
vi.mock('../src/lib/managedZev', () => ({ useManagedZev: () => ({ selectedZevId: 'z1', selectedZev: { id: 'z1', name: 'Z1' }, entries: [] }) }))
const mockUser = vi.hoisted(() => vi.fn())
vi.mock('../src/lib/auth', () => ({ useAuth: () => ({ user: mockUser() }) }))

const live = vi.hoisted(() => ({
    fetchLiveEnabled: vi.fn(),
    fetchLiveSnapshotOrNull: vi.fn(),
    fetchLiveCurveOrNull: vi.fn(),
    fetchOwnSeries: vi.fn(),
    fetchProductionForecastOrNull: vi.fn(),
}))
vi.mock('../src/lib/api/live', () => live)
const eligibleApi = vi.hoisted(() => ({ fetchEligibleOrNull: vi.fn(), listSupplementarySources: vi.fn() }))
vi.mock('../src/lib/api/supplementary', () => eligibleApi)
const zevApi = vi.hoisted(() => ({ fetchParticipants: vi.fn() }))
vi.mock('../src/lib/api/zev', () => zevApi)

const cleanups: Array<() => void> = []
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))

const gross = (overrides: Partial<GrossEnergy> = {}): GrossEnergy => ({
    source_provider: 'solar_manager', covered_from: '2026-10-30T00:00:00Z', covered_to: '2026-10-30T10:00:00Z', coverage_pct: 100,
    production_kwh: 10, consumption_kwh: 5, import_kwh: 1, export_kwh: 6, self_consumption_kwh: 4,
    self_consumption_rate: 40, self_sufficiency_rate: 80, rates_withheld_reason: null,
    timeline: [{ bucket: '2026-10-30T07:00:00+00:00', production_kwh: 0.5, consumption_kwh: 0.25, import_kwh: 0, export_kwh: 0.25, self_consumption_kwh: 0.25 }],
    ...overrides,
})
const series = (overrides: Partial<OwnSeries> = {}): OwnSeries => ({
    participant_id: null, date_from: '2026-10-30', date_to: '2026-10-30', bucket: 'quarter',
    history_through: '2026-10-30T08:00:00Z', gross: gross(), ...overrides,
})
const point = (source: string | null, participant = 'p-me'): EligibleMeteringPoint =>
    ({ metering_point: 'mp', meter_id: 'CH-1', zev: 'z1', zev_name: 'Z1', participant, source })
const snapshot = (liveSources: number): LiveSnapshot => ({
    zev_id: 'z1', as_of: '2026-10-30T11:02:10Z', tier: 'exact', consumption_basis: 'all_points', production_w: 8000, consumption_w: 5000,
    surplus_w: 3000, grid_import_w: 0, local_share_pct: 100,
    coverage: { producing_points: 1, producing_fresh: 1, consuming_points: 1, consuming_fresh: 1, connection_point: null, live_sources: liveSources, points: 2, points_fresh: 2 },
    own: null, max_age_s: 60,
})

describe('range and period helpers', () => {
    it('falls back to today for anything but the other views', () => {
        expect(parseMyEnergyRange('week')).toBe('week')
        expect(parseMyEnergyRange('tomorrow')).toBe('tomorrow')
        expect(parseMyEnergyRange('period')).toBe('period')
        expect(parseMyEnergyRange('nope')).toBe('today')
        expect(parseMyEnergyRange(null)).toBe('today')
    })

    it('counts civil days without a DST shift', () => {
        expect(shiftIsoDate('2026-10-26', -2)).toBe('2026-10-24')
        expect(lastDaysRange('2026-10-27', 7)).toEqual({ from: '2026-10-21', to: '2026-10-27' })
        expect(lastDaysRange('2026-03-30', 7)).toEqual({ from: '2026-03-24', to: '2026-03-30' })
    })
})

describe('showMyEnergyEntry', () => {
    const base = { liveEnabled: false, energyDataOn: false, isZevScope: false, holdsHistoryMeter: false }
    it.each([
        [{ liveEnabled: true }, true],
        [{}, false],
        [{ energyDataOn: true }, false],
        [{ energyDataOn: true, isZevScope: true }, true],
        [{ energyDataOn: true, holdsHistoryMeter: true }, true],
        [{ isZevScope: true, holdsHistoryMeter: true }, false], // the feature is off: nothing to show
    ])('%j -> %s', (input, expected) => {
        expect(showMyEnergyEntry({ ...base, ...input })).toBe(expected)
    })
})

describe('ownHistoryFromSeries', () => {
    it('turns quarter-hour energy into mean power and keeps the hand-over', () => {
        const { rows, through } = ownHistoryFromSeries(series())
        expect(rows).toEqual([{ start: '2026-10-30T07:00:00+00:00', consumption_w: 1000, production_w: 2000 }])
        expect(through).toBe('2026-10-30T08:00:00Z')
    })

    it('is empty without a series or without data', () => {
        expect(ownHistoryFromSeries(null)).toEqual({ rows: [], through: null })
        expect(ownHistoryFromSeries(series({ gross: null, history_through: null }))).toEqual({ rows: [], through: null })
    })
})

describe('todayRows (history first, live after, otherwise a gap)', () => {
    const curve: LiveCurve = {
        date: '2026-10-30', bucket_s: 300, own_history: [], own_history_through: null,
        buckets: [
            { start: '2026-10-30T07:45:00Z', tier: 'exact', production_w: 8000, consumption_w: 5000, own_consumption_w: 700 },
            { start: '2026-10-30T08:00:00Z', tier: 'exact', production_w: 8000, consumption_w: 5000, own_consumption_w: 900, own_production_w: 100 },
            { start: '2026-10-30T08:05:00Z', tier: 'none' },
        ],
    }
    const history = [
        { start: '2026-10-30T07:30:00Z', consumption_w: 1000, production_w: 0 },
        { start: '2026-10-30T07:45:00Z', consumption_w: 1100, production_w: 0 },
    ]
    const at = (rows: ReturnType<typeof todayRows>, iso: string) => rows.find((row) => row.ts === Date.parse(iso))!

    it('prefers history before the hand-over and live from it on', () => {
        const rows = todayRows(curve, history, '2026-10-30T08:00:00Z')

        const before = at(rows, '2026-10-30T07:45:00Z')
        expect([before.ownHistory, before.ownLive]).toEqual([1.1, null]) // live 0.7 loses to history
        const after = at(rows, '2026-10-30T08:00:00Z')
        expect(after.ownLive).toBe(0.9)
        expect(after.ownLiveProduction).toBe(0.1)
        expect(after.ownHistory).toBe(1.1) // the history line is carried to the hand-over so it ends where live begins
    })

    it('leaves a gap where neither source has a value and never fills it', () => {
        const rows = todayRows(curve, history, '2026-10-30T08:00:00Z')

        const gap = at(rows, '2026-10-30T08:05:00Z')
        expect([gap.ownHistory, gap.ownLive, gap.production, gap.consumption]).toEqual([null, null, null, null])
        expect(rows.map((row) => row.ts)).toEqual([...rows.map((row) => row.ts)].sort((a, b) => a - b))
    })

    it('keeps the ZEV totals live only, and uses all live values when there is no history', () => {
        const rows = todayRows(curve, [], null)

        expect(at(rows, '2026-10-30T07:45:00Z')).toMatchObject({ production: 8, consumption: 5, ownLive: 0.7, ownHistory: null })
    })

    it('keeps the history line connected across the 5-minute live grid and leaves a missing interval a gap', () => {
        const grid = Array.from({ length: 12 }, (_, i) => ({
            start: new Date(Date.parse('2026-10-30T07:00:00Z') + i * 300_000).toISOString(), tier: 'none' as const,
        }))
        const rows = todayRows({ ...curve, buckets: grid }, [
            { start: '2026-10-30T07:00:00Z', consumption_w: 1000, production_w: 0 },
            { start: '2026-10-30T07:30:00Z', consumption_w: 2000, production_w: 0 }, // 07:15 is missing
        ], '2026-10-30T08:00:00Z')

        expect(rows.slice(0, 3).map((row) => row.ownHistory)).toEqual([1, 1, 1])
        expect(at(rows, '2026-10-30T07:15:00Z').ownHistory).toBeNull()
        expect(at(rows, '2026-10-30T07:30:00Z').ownHistory).toBe(2)
    })

    it('works from history alone, without a curve', () => {
        const rows = todayRows(null, history, '2026-10-30T08:00:00Z')

        // Each quarter hour is flat across its three 5-minute steps; the last value is carried to the hand-over.
        expect(rows.map((row) => row.ownHistory)).toEqual([1, 1, 1, 1.1, 1.1, 1.1, 1.1])
        expect(rows.every((row) => row.production === null && row.ownLive === null)).toBe(true)
    })
})

async function render(period = { from: '2026-10-01', to: '2026-10-31' }) {
    const rendered = await renderWithProviders(
        createElement(MyEnergyView, { interval: 'monthly', period, onPeriodChange: () => {}, periodReady: true }),
        cleanups,
    )
    for (let tick = 0; tick < 5; tick += 1) await act(async () => { await new Promise((resolve) => setTimeout(resolve, 10)) })
    return rendered
}

const clickTab = async (container: Element, index: number) => {
    await act(async () => { container.querySelectorAll('[role="tab"]')[index].dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    for (let tick = 0; tick < 4; tick += 1) await act(async () => { await new Promise((resolve) => setTimeout(resolve, 10)) })
}

beforeEach(() => {
    vi.clearAllMocks()
    mockAccess.mockReturnValue({ isZevScope: false, isParticipantScope: true })
    mockUser.mockReturnValue({ memberships: [{ zev: 'z1', participants: [{ id: 'p-me', live: true }] }] })
    live.fetchLiveEnabled.mockResolvedValue(false)
    live.fetchLiveSnapshotOrNull.mockResolvedValue(null)
    live.fetchLiveCurveOrNull.mockResolvedValue(null)
    live.fetchOwnSeries.mockResolvedValue(series())
    live.fetchProductionForecastOrNull.mockResolvedValue(null)
    eligibleApi.fetchEligibleOrNull.mockResolvedValue([point('s1')])
    eligibleApi.listSupplementarySources.mockResolvedValue([])
    zevApi.fetchParticipants.mockResolvedValue([
        { id: 'p-me', zev: 'z1', display_name: 'Me', valid_to: null },
        { id: 'p-other', zev: 'z1', display_name: 'Other', valid_to: null },
        { id: 'p-gone', zev: 'z1', display_name: 'Gone', valid_to: '2020-01-01' },
        { id: 'p-else', zev: 'z2', display_name: 'Elsewhere', valid_to: null },
    ])
})

describe('MyEnergyView', () => {
    it('says so, and asks for no history, while the energy data feature is off', async () => {
        eligibleApi.fetchEligibleOrNull.mockResolvedValue(null)
        const { container } = await render()

        expect(container.textContent).toContain('myEnergy.disabled')
        expect(live.fetchOwnSeries).not.toHaveBeenCalled()
    })

    it('starts the live requests without waiting for the eligibility check', async () => {
        eligibleApi.fetchEligibleOrNull.mockReturnValue(new Promise(() => {}))
        await render()

        expect(live.fetchLiveEnabled).toHaveBeenCalled()
        expect(live.fetchLiveSnapshotOrNull).toHaveBeenCalledWith('z1')
        expect(live.fetchProductionForecastOrNull).toHaveBeenCalledWith('z1')
    })

    it('shows a participant their own history for today with live off, from the own-series endpoint', async () => {
        const { container } = await render()

        expect(live.fetchLiveCurveOrNull).not.toHaveBeenCalled()
        expect(live.fetchOwnSeries).toHaveBeenCalledWith({
            zevId: 'z1', dateFrom: todayBusinessIso(), dateTo: todayBusinessIso(), bucket: 'quarter', participantId: undefined,
        })
        expect(container.querySelector('.chart-card')).not.toBeNull()
        expect(container.querySelector('.empty-state')).toBeNull()
    })

    it('takes the own history from the live curve, and does not ask the own-series endpoint, while live has data', async () => {
        live.fetchLiveEnabled.mockResolvedValue(true)
        live.fetchLiveSnapshotOrNull.mockResolvedValue(snapshot(2))
        live.fetchLiveCurveOrNull.mockResolvedValue({
            date: todayBusinessIso(), bucket_s: 300, buckets: [],
            own_history: [{ start: '2026-10-30T07:00:00+00:00', consumption_w: 1000, production_w: 0 }],
            own_history_through: '2026-10-30T07:15:00Z',
        })
        const { container } = await render()

        expect(live.fetchLiveCurveOrNull).toHaveBeenCalledWith('z1', todayBusinessIso(), undefined)
        expect(live.fetchOwnSeries).not.toHaveBeenCalled()
        expect(container.textContent).toContain('live.title')
    })

    it('falls back to the history alone when the live curve is not available', async () => {
        live.fetchLiveEnabled.mockResolvedValue(true)
        live.fetchLiveSnapshotOrNull.mockResolvedValue(snapshot(2))
        live.fetchLiveCurveOrNull.mockResolvedValue(null)
        await render()

        expect(live.fetchOwnSeries).toHaveBeenCalledTimes(1)
    })

    it('offers a participant without a connected system the call to action, and others an explanation', async () => {
        eligibleApi.fetchEligibleOrNull.mockResolvedValue([point(null)])
        live.fetchOwnSeries.mockResolvedValue(series({ gross: null, history_through: null }))
        const { container } = await render()
        expect(container.textContent).toContain('supplementary.gross.ctaTitle')
    })

    it('promises a participant without a plant behind the meter no own history, and offers no empty views', async () => {
        eligibleApi.fetchEligibleOrNull.mockResolvedValue([])
        live.fetchLiveEnabled.mockResolvedValue(true)
        live.fetchLiveSnapshotOrNull.mockResolvedValue(snapshot(0))
        live.fetchOwnSeries.mockResolvedValue(series({ gross: null, history_through: null }))
        const { container } = await render()

        expect(container.textContent).not.toContain('supplementary.gross.ctaTitle')
        expect(container.textContent).not.toContain('myEnergy.noOwnSystem')
        expect(container.querySelectorAll('[role="tab"]')).toHaveLength(0)
        expect(container.querySelector('.chart-card')).toBeNull()
    })

    it('shows the last seven civil days in hourly buckets on the 7 days tab, with the pointer to Energy balance', async () => {
        const { container } = await render()
        await clickTab(container, 1)

        const today = todayBusinessIso()
        expect(live.fetchOwnSeries).toHaveBeenLastCalledWith({
            zevId: 'z1', dateFrom: lastDaysRange(today, 7).from, dateTo: today, bucket: 'hour', participantId: undefined,
        })
        expect(container.textContent).toContain('supplementary.gross.titleOwn')
        expect(container.textContent).toContain('myEnergy.week.note')
        expect(container.querySelector('a[href="/dashboard"]')).not.toBeNull()
    })

    it('shows the billing period in daily buckets on the Period tab', async () => {
        const { container } = await render()
        await clickTab(container, 2)

        expect(live.fetchOwnSeries).toHaveBeenLastCalledWith({
            zevId: 'z1', dateFrom: '2026-10-01', dateTo: '2026-10-31', bucket: 'day', participantId: undefined,
        })
        expect(container.textContent).toContain('supplementary.gross.titleOwn')
    })

    describe('as a manager', () => {
        beforeEach(() => {
            mockAccess.mockReturnValue({ isZevScope: true, isParticipantScope: false })
            mockUser.mockReturnValue({ memberships: [{ zev: 'z1', participants: [] }] })
        })

        const historySource = (participant = 'p-other') =>
            ({ id: 's1', zev: 'z1', target: 'metering_point', participant, provides_history: true, provides_live: false })

        it('asks nobody\'s figures until a participant is picked, and lists only current participants of the ZEV', async () => {
            eligibleApi.fetchEligibleOrNull.mockResolvedValue([])
            eligibleApi.listSupplementarySources.mockResolvedValue([historySource()])
            const { container } = await render()

            expect(live.fetchOwnSeries).not.toHaveBeenCalled()
            const options = Array.from(container.querySelectorAll('select option')).map((option) => option.textContent)
            expect(options).toEqual(['myEnergy.pickParticipant', 'Me', 'Other'])
        })

        it('puts the participant picker before the tabs it steers, and does not repeat its placeholder as a helper', async () => {
            eligibleApi.listSupplementarySources.mockResolvedValue([historySource()])
            const { container } = await render()

            const picker = container.querySelector('select')!
            const tabs = container.querySelector('[role="tablist"]')!
            expect(picker.compareDocumentPosition(tabs) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
            expect(container.querySelector('.filter-bar-note')).toBeNull()
        })

        it('offers no tabs and no picker where no source can provide a history, live data or a forecast', async () => {
            eligibleApi.fetchEligibleOrNull.mockResolvedValue([])
            live.fetchLiveEnabled.mockResolvedValue(true)
            live.fetchLiveSnapshotOrNull.mockResolvedValue(snapshot(0))
            eligibleApi.listSupplementarySources.mockResolvedValue([{ ...historySource(), provides_history: false }, { ...historySource(), zev: 'z2' }])
            const { container } = await render()

            expect(container.querySelector('.empty-state')).not.toBeNull()
            expect(container.querySelectorAll('[role="tab"]')).toHaveLength(0)
            expect(container.querySelector('select')).toBeNull()
        })

        it('tells two participants with the same name apart by their e-mail', async () => {
            eligibleApi.fetchEligibleOrNull.mockResolvedValue([])
            eligibleApi.listSupplementarySources.mockResolvedValue([historySource()])
            zevApi.fetchParticipants.mockResolvedValue([
                { id: 'p-1', zev: 'z1', display_name: 'Ben', email: 'ben@a.test', valid_to: null },
                { id: 'p-2', zev: 'z1', display_name: 'Ben', email: 'ben@b.test', valid_to: null },
                { id: 'p-3', zev: 'z1', display_name: 'Anna', email: 'anna@a.test', valid_to: null },
            ])
            const { container } = await render()

            expect(Array.from(container.querySelectorAll('select option')).map((option) => option.textContent))
                .toEqual(['myEnergy.pickParticipant', 'Ben · ben@a.test', 'Ben · ben@b.test', 'Anna'])
        })

        it('speaks of the person, not of "you", while looking at somebody else', async () => {
            eligibleApi.listSupplementarySources.mockResolvedValue([historySource()])
            const { container } = await render()
            await act(async () => {
                const select = container.querySelector('select') as HTMLSelectElement
                Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')!.set!.call(select, 'p-other')
                select.dispatchEvent(new Event('change', { bubbles: true }))
            })
            await clickTab(container, 1)

            expect(container.textContent).toContain('myEnergy.week.notePerson')
            expect(container.textContent).not.toContain('myEnergy.week.note|')
        })

        it('starts on the manager themselves when they are a participant with an own system', async () => {
            mockUser.mockReturnValue({ memberships: [{ zev: 'z1', participants: [{ id: 'p-me', live: true }] }] })
            eligibleApi.fetchEligibleOrNull.mockResolvedValue([point('s1', 'p-me')])
            eligibleApi.listSupplementarySources.mockResolvedValue([historySource('p-me')])
            const { container } = await render()

            expect(live.fetchOwnSeries).toHaveBeenCalledWith(expect.objectContaining({ participantId: 'p-me', bucket: 'quarter' }))
            expect((container.querySelector('select') as HTMLSelectElement).value).toBe('p-me')
            expect(Array.from(container.querySelectorAll('select option')).map((option) => option.textContent))
                .toContain('Me (pages.dashboard.youBadge)')
        })
    })
})

describe('the forecast in My energy system', () => {
    const noon = (isoDate: string, hours = 0) => new Date(businessDayStartMs(isoDate) + (12 + hours) * 3_600_000).toISOString()
    const forecast = (days: string[]): ProductionForecast => ({
        zev_id: 'z1', horizon_h: 72, complete: true, plants: 1, plants_with_forecast: 1, fetched_at: new Date().toISOString(),
        hours: days.flatMap((day) => [0, 1].map((h) => ({ start: noon(day, h), power_w: 4000 + h * 1000, min_w: 3000, max_w: 5000 }))),
        // Today's window ends in the future whatever the time of day: it is only named while it is still ahead.
        peak_windows: days.map((day) => ({
            date: day,
            from: noon(day),
            to: day === todayBusinessIso() ? new Date(Date.now() + 3_600_000).toISOString() : noon(day, 2),
            peak_w: 5000,
        })),
    })
    const tabLabels = (container: Element) => Array.from(container.querySelectorAll('[role="tab"]')).map((tab) => tab.textContent)

    beforeEach(() => {
        live.fetchLiveEnabled.mockResolvedValue(true)
    })

    describe('todayRows', () => {
        it('draws each forecast hour flat across its 5-minute steps, with its band, for the given day only', () => {
            const day = todayBusinessIso()
            const rows = todayRows(null, [], null, {
                date: day,
                hours: [
                    { start: noon(day), power_w: 4000, min_w: 3000, max_w: 5000 },
                    { start: noon(shiftIsoDate(day, 1)), power_w: 9000, min_w: null, max_w: null },
                ],
            })
            expect(rows).toHaveLength(12)
            expect(rows.every((row) => row.forecast === 4 && row.forecastBand?.[0] === 3 && row.forecastBand[1] === 5)).toBe(true)
            expect(rows.every((row) => row.production === null && row.ownHistory === null)).toBe(true)
        })

        it('has no forecast without one', () => {
            expect(todayRows(null, history0, null).every((row) => row.forecast === null && row.forecastBand === null)).toBe(true)
        })
    })

    it('shows the forecast with today, also when there is no live data and no own system', async () => {
        const day = todayBusinessIso()
        live.fetchProductionForecastOrNull.mockResolvedValue(forecast([day]))
        live.fetchOwnSeries.mockResolvedValue(series({ gross: null, history_through: null }))
        eligibleApi.fetchEligibleOrNull.mockResolvedValue([])
        const { container } = await render()

        expect(container.querySelector('.chart-card')).not.toBeNull()
        expect(container.textContent).toContain('forecast.peak.today')
        expect(tabLabels(container)).toEqual([])
    })

    it('offers a Tomorrow tab with the forecast alone once there is a forecast for tomorrow', async () => {
        const tomorrow = shiftIsoDate(todayBusinessIso(), 1)
        live.fetchProductionForecastOrNull.mockResolvedValue(forecast([todayBusinessIso(), tomorrow]))
        const { container } = await render()

        expect(tabLabels(container)).toEqual(['myEnergy.tabs.today', 'myEnergy.tabs.tomorrow', 'myEnergy.tabs.week', 'myEnergy.tabs.period'])
        live.fetchOwnSeries.mockClear()
        await clickTab(container, 1)

        expect(container.textContent).toContain('myEnergy.tomorrow.title')
        expect(container.textContent).toContain('forecast.hint')
        expect(live.fetchOwnSeries).not.toHaveBeenCalled()
    })

    it('has no Tomorrow tab when the forecast has nothing for tomorrow or is all dark', async () => {
        live.fetchProductionForecastOrNull.mockResolvedValue(forecast([todayBusinessIso()]))
        expect(tabLabels((await render()).container)).not.toContain('myEnergy.tabs.tomorrow')
        cleanups.splice(0).forEach((cleanup) => cleanup())

        const dark = forecast([todayBusinessIso(), shiftIsoDate(todayBusinessIso(), 1)])
        dark.hours = dark.hours.map((hour) => ({ ...hour, power_w: 0 }))
        live.fetchProductionForecastOrNull.mockResolvedValue(dark)
        expect(tabLabels((await render()).container)).not.toContain('myEnergy.tabs.tomorrow')
    })
})

const history0 = [{ start: '2026-10-30T07:30:00Z', consumption_w: 1000, production_w: 0 }]
