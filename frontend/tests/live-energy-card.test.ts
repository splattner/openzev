import { createElement } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { LiveCurveChart } from '../src/features/live/LiveCurveChart'
import { LiveEnergyCard } from '../src/features/live/LiveEnergyCard'
import { LivePointsTable } from '../src/features/live/LivePointsTable'
import type { LiveOwn, LivePoint, LiveSnapshot } from '../src/types/api'
import { renderWithProviders } from './helpers/render'

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
    coverage: { producing_points: 1, producing_fresh: 1, consuming_points: 6, consuming_fresh: 1, connection_point: 'fresh', live_sources: 2 },
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

    it('gives a manager the reason when production is not covered', async () => {
        const out = await text(none({ coverage: { ...none().coverage, producing_points: 2, producing_fresh: 1 }, points: [] }))

        expect(out).toContain('live.noneReason|{"fresh":1,"total":2}')
    })

    it('shows only the production and the note at tier production', async () => {
        const out = await text(production())

        expect(out).toContain('live.zevProduces|{"value":"8.0\u00a0kW"}')
        expect(out).toContain('live.othersUnknown')
        expect(out).not.toContain('live.spare')
        expect(out).not.toContain('live.localShare')
        expect(out).not.toContain('live.ownSplit')
        // The viewer's own consumption is measured, so it is shown, but no split.
        expect(out).toContain('live.ownConsumption|{"value":"1.2\u00a0kW"}')
    })

    it('leaves the own consumption out while the viewer\'s points are incomplete', async () => {
        const out = await text(production({ own: own({ complete: false, consumption_w: null, local_w: null, grid_w: null }) }))

        expect(out).not.toContain('live.ownConsumption')
    })

    it('shows production, consumption, spare power, share and the own split at tier exact', async () => {
        const out = await text(exact())

        expect(out).toContain('live.production')
        expect(out).toContain('live.consumption')
        expect(out).toContain('live.spare')
        expect(out).toContain('3.0')
        expect(out).toContain('live.localShare')
        expect(out).toContain('live.ownSplit|{"total":"1.2\u00a0kW","local":"1.2\u00a0kW","grid":"0.0\u00a0kW"}')
        expect(out).toContain('live.basisConnectionPoint')
        expect(out).not.toContain('live.othersUnknown')
    })

    it('shows a hint instead of an inconsistent split', async () => {
        const out = await text(exact({ own: own({ local_w: null, grid_w: null, split_withheld_reason: 'inconsistent' }) }))

        expect(out).toContain('live.ownSplitInconsistent')
        expect(out).not.toContain('live.ownSplit|')
        expect(out).toContain('live.ownConsumption')
    })

    it('shows how a producer\'s own production is shared at tier exact', async () => {
        const out = await text(exact({ own: own({ consumption_w: null, local_w: null, grid_w: null, production_w: 4000, to_zev_w: 3000, to_grid_w: 1000 }) }))

        expect(out).toContain('live.ownProductionSplit|{"total":"4.0\u00a0kW","toZev":"3.0\u00a0kW","toGrid":"1.0\u00a0kW"}')
    })

    it('shows the time of the oldest value and the coverage with the connection point', async () => {
        const out = await text(exact())

        expect(out).toContain('live.asOf|{"time":"12:02:10"}')
        expect(out).toContain('live.badge')
        expect(out).toContain('live.coverage|{"fresh":1,"total":6}')
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
        expect(out).toContain('1.2\u00a0kW')
        expect(out).toContain('live.points.seconds|{"count":7}')
        expect(out).toContain('live.points.connection')
        expect(out).toContain('live.points.zevOperated')
        expect(container.querySelector('.badge-success')).not.toBeNull()
        expect(container.querySelector('.badge-warning')).not.toBeNull()
    })
})

describe('LiveCurveChart', () => {
    it('says so when the day has no live values yet', async () => {
        const curve = { date: '2026-10-30', bucket_s: 300, buckets: [{ start: '2026-10-30T07:00:00Z', tier: 'none' as const }] }
        const { container } = await renderWithProviders(createElement(LiveCurveChart, { curve }), cleanups)

        expect(container.textContent).toContain('live.curve.empty')
    })
})
