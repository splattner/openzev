import { createElement } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { LiveEnergyCard } from '../src/features/live/LiveEnergyCard'
import { LivePointsTable } from '../src/features/live/LivePointsTable'
import { TodayChart } from '../src/features/myEnergy/TodayChart'
import type { LiveOwn, LivePoint, LiveSnapshot } from '../src/types/api'
import { renderWithProviders } from './helpers/render'

const mockAccess = vi.hoisted(() => vi.fn(() => ({ canManage: true })))
vi.mock('../src/lib/communityAccess', () => ({ useCommunityAccess: () => mockAccess() }))

// The mock prints the key and its values, so a test sees which text the card chose.
vi.mock('react-i18next', () => ({
    useTranslation: () => ({
        t: (key: string, options?: Record<string, unknown>) => (options ? `${key}|${JSON.stringify(options)}` : key),
    }),
}))

const cleanups: Array<() => void> = []
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))

const own = (overrides: Partial<LiveOwn> = {}): LiveOwn => ({
    consumption_w: 1200,
    local_w: 1200,
    grid_w: 0,
    production_w: null,
    to_zev_w: null,
    to_grid_w: null,
    gross: { production_w: null, consumption_w: null },
    complete: true,
    points: 1,
    points_fresh: 1,
    ...overrides,
})

const exact = (overrides: Partial<LiveSnapshot> = {}): LiveSnapshot => ({
    zev_id: 'z1',
    as_of: '2026-10-30T11:02:10Z',
    tier: 'exact',
    consumption_basis: 'connection_point',
    production_w: 8000,
    consumption_w: 5000,
    surplus_w: 3000,
    grid_import_w: 0,
    local_share_pct: 100,
    coverage: { producing_points: 1, producing_fresh: 1, consuming_points: 6, consuming_fresh: 1, connection_point: 'fresh', live_sources: 2, points: 7, points_fresh: 2 },
    own: own(),
    max_age_s: 60,
    ...overrides,
})

const production = (overrides: Partial<LiveSnapshot> = {}): LiveSnapshot =>
    exact({
        tier: 'production',
        consumption_basis: null,
        consumption_w: null,
        surplus_w: null,
        grid_import_w: null,
        local_share_pct: null,
        own: own({ local_w: null, grid_w: null }),
        ...overrides,
    })

const none = (overrides: Partial<LiveSnapshot> = {}): LiveSnapshot =>
    production({ tier: 'none', as_of: null, production_w: null, own: null, ...overrides })

const text = async (snapshot: LiveSnapshot) => {
    const { container } = await renderWithProviders(createElement(LiveEnergyCard, { snapshot }), cleanups)
    return container.textContent ?? ''
}

describe('LiveEnergyCard', () => {
    it('says there is no live production data at tier none, without a reason for a participant', async () => {
        const out = await text(none())

        expect(out).toContain('live.none')
        expect(out).not.toContain('live.noneReason')
        expect(out).not.toContain('live.asOf')
        expect(out).not.toContain('live.zevProduces')
    })

    it('says the distinct point coverage once, for participants and managers alike', async () => {
        // A vZEV of three bidirectional meters: per role the payload says 1 of 3 twice; the distinct count is said once.
        const coverage = { ...none().coverage, producing_points: 3, producing_fresh: 1, consuming_points: 3, consuming_fresh: 1, points: 3, points_fresh: 1 }
        const out = await text(none({ coverage }))

        expect(out).toContain('live.none')
        expect(out).toContain('live.coverage|{"fresh":1,"total":3}')
        expect(out.match(/live\.coverage/g)).toHaveLength(1)
        expect(out).toContain('live.connectionPoint')
    })

    it('shows only the production and the note at tier production', async () => {
        const out = await text(production())

        expect(out).toContain('live.zevProduces|{"value":"8.0\u00a0kW"}')
        expect(out).toContain('live.othersUnknown')
        expect(out).not.toContain('live.spare')
        expect(out).not.toContain('live.localShare')
        expect(out).not.toContain('live.ownSplitHint')
        // The viewer's own consumption is measured, so it is shown as a figure of its own, but with no split.
        expect(out).toContain('live.ownConsumptionLabel')
        expect(out).toContain('1.2')
        expect(out).not.toContain('live.ownSplitHint')
    })

    it('leaves the own consumption out while the viewer\'s points are incomplete', async () => {
        const out = await text(production({ own: own({ complete: false, consumption_w: null, local_w: null, grid_w: null }) }))

        expect(out).not.toContain('live.ownConsumptionLabel')
    })

    it('shows production, consumption, spare power, share and the own split at tier exact', async () => {
        const out = await text(exact())

        expect(out).toContain('live.production')
        expect(out).toContain('live.consumption')
        expect(out).toContain('live.spare')
        expect(out).toContain('3.0')
        expect(out).toContain('live.localShare')
        expect(out).toContain('live.ownConsumptionLabel')
        expect(out).toContain('live.ownSplitHint|{"local":"1.2\u00a0kW","grid":"0.0\u00a0kW"}')
        expect(out).toContain('live.basisConnectionPoint')
        expect(out).not.toContain('live.othersUnknown')
    })

    it('shows a hint instead of an inconsistent split', async () => {
        const out = await text(exact({ own: own({ local_w: null, grid_w: null, split_withheld_reason: 'inconsistent' }) }))

        expect(out).toContain('live.ownSplitInconsistent')
        expect(out).not.toContain('live.ownSplitHint')
        expect(out).toContain('live.ownConsumptionLabel')
    })

    it('shows how a producer\'s own production is shared at tier exact', async () => {
        const out = await text(exact({ own: own({ consumption_w: null, local_w: null, grid_w: null, production_w: 4000, to_zev_w: 3000, to_grid_w: 1000 }) }))

        expect(out).toContain('live.ownProductionLabel')
        expect(out).toContain('live.ownProductionSplitHint|{"toZev":"3.0\u00a0kW","toGrid":"1.0\u00a0kW"}')
    })

    it('shows the time of the oldest value and the coverage with the connection point', async () => {
        const out = await text(exact())

        expect(out).toContain('live.asOf|{"time":"12:02:10"}')
        expect(out).toContain('live.badge')
        expect(out).toContain('live.coverage|{"fresh":2,"total":7}')
        expect(out).toContain('live.connectionPoint')
        expect(out).toContain('live.state.fresh')
    })

    it('shows no connection point line without such a source', async () => {
        const base = exact()
        const out = await text(exact({ coverage: { ...base.coverage, connection_point: null } }))

        expect(out).not.toContain('live.connectionPoint')
    })

    it('never prints a value the payload leaves out', async () => {
        const out = await text(exact({ local_share_pct: null }))

        expect(out).toContain('—')
    })
})

describe('LivePointsTable', () => {
    const point = (overrides: Partial<LivePoint>): LivePoint => ({
        metering_point_id: 'm1',
        target: 'metering_point',
        meter_id: 'CH-1',
        meter_type: 'consumption',
        participant_name: 'Anna',
        held_by: 'participant',
        live_state: 'fresh',
        meter_power_w: 1200,
        age_s: 7,
        source_id: 's1',
        ...overrides,
    })

    it('lists the meter, the holder, the power, the age and the state', async () => {
        const rows = [
            point({}),
            point({ metering_point_id: null, target: 'connection_point', meter_id: null, participant_name: null, held_by: 'zev', source_id: 's2', live_state: 'stale', meter_power_w: null, age_s: null }),
        ]
        const { container } = await renderWithProviders(createElement(LivePointsTable, { points: rows }), cleanups)

        const out = container.textContent ?? ''
        expect(out).toContain('CH-1')
        expect(out).toContain('Anna')
        expect(out).toContain('live.points.flow.consumed|{"value":"1.2\u00a0kW"}')
        expect(out).toContain('live.points.seconds|{"count":7}')
        expect(out).toContain('live.points.connection')
        expect(out).toContain('live.points.zevOperated')
        // A current value is plain text, never a coloured pill; only a source gone quiet is flagged (UI patterns §10.1).
        expect(container.querySelector('.badge')).toBeNull()
        expect(container.querySelectorAll('.issue-text--warning')).toHaveLength(2)
        expect(out).toContain('live.state.fresh')
    })

    it('also lists each point as a small card for a phone, with the value in it', async () => {
        const { container } = await renderWithProviders(createElement(LivePointsTable, { points: [point({})] }), cleanups)

        const card = container.querySelector('.live-points-list li')
        expect(card?.textContent).toContain('CH-1')
        expect(card?.textContent).toContain('live.points.flow.consumed|{"value":"1.2\u00a0kW"}')
        expect(card?.textContent).toContain('live.points.seconds|{"count":7}')
    })

    it('says the direction in words and never prints the meter\'s minus', async () => {
        const rows = [
            point({ meter_type: 'production', meter_power_w: -6200 }),
            point({ metering_point_id: null, target: 'connection_point', meter_id: null, meter_type: null, meter_power_w: -2000, source_id: 's2' }),
            point({ metering_point_id: 'm3', meter_id: 'CH-3', meter_power_w: 30 }),
        ]
        const { container } = await renderWithProviders(createElement(LivePointsTable, { points: rows }), cleanups)

        const out = container.querySelector('table')?.textContent ?? ''
        expect(out).toContain('live.points.flow.produced|{"value":"6.2\u00a0kW"}')
        expect(out).toContain('live.points.flow.toGrid|{"value":"2.0\u00a0kW"}')
        // Below the display resolution there is no direction.
        expect(out).toContain('0.0\u00a0kW')
        expect(out).not.toMatch(/-\d+\.\d/)
    })

    it('summarises how many points report, open only while some do not', async () => {
        const partial = [point({}), point({ metering_point_id: 'm2', meter_id: 'CH-2', live_state: 'never', source_id: null, meter_power_w: null, age_s: null })]
        const { container } = await renderWithProviders(createElement(LivePointsTable, { points: partial }), cleanups)
        expect(container.querySelector('summary')?.textContent).toContain('live.points.summary|{"live":1,"total":2}')
        expect(container.querySelector('details')?.open).toBe(true)

        const complete = await renderWithProviders(createElement(LivePointsTable, { points: [point({})] }), cleanups)
        expect(complete.container.querySelector('details')?.open).toBe(false)
    })

    it('offers a manager the way to connect a point nobody holds, and tells a viewer or a holder\'s point nothing to do', async () => {
        const open = point({ meter_id: 'CH-9', participant_name: null, held_by: null, source_id: null, live_state: 'never', meter_power_w: null, age_s: null })
        const held = point({ metering_point_id: 'm2', meter_id: 'CH-2', source_id: null, live_state: 'never', meter_power_w: null, age_s: null })
        const manager = await renderWithProviders(createElement(LivePointsTable, { points: [open, held] }), cleanups)
        const link = manager.container.querySelector('table a')
        expect(link?.getAttribute('href')).toBe('/zev-settings/energy')
        expect(manager.container.querySelectorAll('table a')).toHaveLength(1)
        expect(manager.container.querySelector('table')?.textContent).toContain('live.points.holderConnects')

        mockAccess.mockReturnValueOnce({ canManage: false })
        const viewer = await renderWithProviders(createElement(LivePointsTable, { points: [open] }), cleanups)
        expect(viewer.container.querySelector('table a')).toBeNull()
    })
})

describe('TodayChart', () => {
    it('says so when the day has no values yet', async () => {
        const { container } = await renderWithProviders(
            createElement(TodayChart, { date: '2026-10-30', rows: [], through: null, hasLive: true }),
            cleanups,
        )

        expect(container.textContent).toContain('myEnergy.today.empty')
    })

    it('says there is no own data today when only the history was asked for', async () => {
        const { container } = await renderWithProviders(
            createElement(TodayChart, { date: '2026-10-30', rows: [], through: null, hasLive: false }),
            cleanups,
        )

        expect(container.textContent).toContain('myEnergy.today.emptyHistory')
    })
})
