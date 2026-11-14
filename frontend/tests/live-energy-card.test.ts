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
        expect(out).not.toContain('live.production')
    })

    it('shows the own figures at tier none and says only that the ZEV as a whole has no data', async () => {
        // vZEV where only the viewer's point reports: the viewer's own readings stand on their own.
        const out = await text(none({ own: own({ consumption_w: 400, production_w: 0, local_w: null, grid_w: null }) }))

        expect(out).toContain('live.ownConsumptionLabel')
        expect(out).toContain('0.4')
        expect(out).toContain('live.ownProductionLabel')
        expect(out).toContain('live.noneZev')
        expect(out.replace('live.noneZev', '')).not.toContain('live.none')
        expect(out).not.toContain('live.ownSplitHint')
    })

    it('prefers the gross figures of a system behind the meter over the metered surplus', async () => {
        // Metered: 3 kW fed out, nothing drawn. The system itself reports 3.4 kW produced and 0.4 kW used.
        const out = await text(exact({ own: own({ consumption_w: 0, production_w: 3000, local_w: 0, grid_w: 0, to_zev_w: 3000, to_grid_w: 0, gross: { production_w: 3400, consumption_w: 400 } }) }))

        expect(out).toContain('0.4')
        expect(out).toContain('3.4')
        // The split belongs to the metered power, so it is not printed beside a gross figure.
        expect(out).not.toContain('live.ownSplitHint')
        expect(out).not.toContain('live.ownProductionSplitHint')
    })

    it('has no coverage line: how many points report is on the per-point table', async () => {
        const coverage = { ...none().coverage, producing_points: 3, producing_fresh: 1, consuming_points: 3, consuming_fresh: 1, points: 3, points_fresh: 1 }
        const out = await text(none({ coverage }))

        expect(out).toContain('live.none')
        expect(out).not.toContain('live.coverage')
        expect(out).not.toContain('live.connectionPoint')
    })

    it('says nothing is spare, not that part of it may be in use, when the ZEV produces nothing', async () => {
        const out = await text(production({ production_w: 0 }))

        expect(out).toContain('live.production')
        expect(out).toContain('0.0')
        expect(out).toContain('live.nothingSpare')
        expect(out).not.toContain('live.othersUnknown')
    })

    it('puts the own and the ZEV tiles into one grid', async () => {
        const { container } = await renderWithProviders(createElement(LiveEnergyCard, { snapshot: exact({ own: own({ production_w: 3000, to_zev_w: 3000, to_grid_w: 0 }) }) }), cleanups)

        expect(container.querySelectorAll('.stat-grid')).toHaveLength(1)
        expect(container.querySelectorAll('.stat-card')).toHaveLength(6)
    })

    it('sets the tiles on the page, not in a white box of their own', async () => {
        const { container } = await renderWithProviders(createElement(LiveEnergyCard, { snapshot: exact() }), cleanups)

        expect(container.querySelector('.card')).toBeNull()
        expect(container.querySelector('.live-now > .stat-grid')).not.toBeNull()
    })

    it('puts the note about the others\' use into a tooltip on the ZEV production tile', async () => {
        const { container } = await renderWithProviders(createElement(LiveEnergyCard, { snapshot: production() }), cleanups)

        const tile = Array.from(container.querySelectorAll('.stat-card')).find((card) => card.textContent?.includes('live.production'))!
        const bubble = tile.querySelector('[role="tooltip"]')!
        expect(bubble.textContent).toBe('live.othersUnknown')
        expect(tile.querySelector('button')!.getAttribute('aria-describedby')).toBe(bubble.id)
        // The note is no paragraph under the tiles any more.
        expect(Array.from(container.querySelectorAll('.live-now > p')).map((p) => p.textContent)).not.toContain('live.othersUnknown')
    })

    it('shows only the production and the note at tier production', async () => {
        const out = await text(production())

        expect(out).toContain('live.production')
        expect(out).toContain('8.0')
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

    it('shows the time of the oldest value, no indicative badge, and no coverage or connection point line', async () => {
        const out = await text(exact())

        expect(out).toContain('live.asOf|{"time":"12:02:10"}')
        expect(out).not.toContain('live.badge')
        expect(out).not.toContain('live.coverage')
        expect(out).not.toContain('live.connectionPoint')
    })

    it('says, with a way to the connection, when the viewer\'s own source has gone quiet and the own tiles are therefore gone', async () => {
        const quiet = await renderWithProviders(
            createElement(LiveEnergyCard, { snapshot: exact({ own: own({ complete: false, points: 1, points_fresh: 0, consumption_w: null, local_w: null, grid_w: null }) }) }),
            cleanups,
        )
        const issue = quiet.container.querySelector('a.issue-text--warning')
        expect(issue?.textContent).toBe('live.ownQuiet')
        expect(issue?.getAttribute('href')).toBe('/me/metering-points')
        expect(quiet.container.textContent).not.toContain('live.ownConsumptionLabel')

        const partly = await renderWithProviders(
            createElement(LiveEnergyCard, { snapshot: exact({ own: own({ complete: false, points: 2, points_fresh: 1 }) }) }),
            cleanups,
        )
        expect(partly.container.querySelector('.issue-text--warning')?.textContent).toBe('live.ownPartlyQuiet|{"fresh":1,"total":2}')

        const fine = await renderWithProviders(createElement(LiveEnergyCard, { snapshot: exact() }), cleanups)
        expect(fine.container.querySelector('.issue-text--warning')).toBeNull()
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

    it('is always open, titled only, and does not count the points without a value in its title', async () => {
        const partial = [
            point({}),
            point({ metering_point_id: 'm2', meter_id: 'CH-2', live_state: 'never', source_id: null, meter_power_w: null, age_s: null }),
            point({ metering_point_id: null, target: 'connection_point', meter_id: null, live_state: 'stale', source_id: 's2' }),
        ]
        const { container } = await renderWithProviders(createElement(LivePointsTable, { points: partial }), cleanups)
        expect(container.querySelector('details')).toBeNull()
        expect(container.querySelector('h3')?.textContent).toBe('live.points.summary')
        expect(container.textContent).not.toContain('live.points.quiet')
        expect(container.querySelectorAll('tbody tr')).toHaveLength(3)
    })

    it('offers a manager the way to connect a point nobody holds, and tells a viewer or a holder\'s point nothing to do', async () => {
        const open = point({ meter_id: 'CH-9', participant_name: null, held_by: null, source_id: null, live_state: 'never', meter_power_w: null, age_s: null })
        const held = point({ metering_point_id: 'm2', meter_id: 'CH-2', source_id: null, live_state: 'never', meter_power_w: null, age_s: null })
        const manager = await renderWithProviders(createElement(LivePointsTable, { points: [open, held] }), cleanups)
        const link = manager.container.querySelector('table a')
        expect(link?.getAttribute('href')).toBe('/zev-settings/energy')
        // A link beside a status must not differ from the text by colour and weight alone (UI patterns §10.3 rule 11).
        expect(link?.classList.contains('text-link')).toBe(true)
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

        expect(container.textContent).toContain('myEnergy.today.ownEmptyHistory')
    })

    it('speaks of the person, not of "you", for a manager looking at somebody else', async () => {
        const { container } = await renderWithProviders(
            createElement(TodayChart, { date: '2026-10-30', rows: [], through: null, hasLive: false, isOwn: false }),
            cleanups,
        )

        expect(container.textContent).toContain('myEnergy.today.personEmptyHistory')
        expect(container.textContent).not.toContain('myEnergy.today.ownEmptyHistory')
    })

    it('has no help text under the chart and no heading repeating the tab', async () => {
        const row = { ts: Date.parse('2026-10-30T10:00:00Z'), production: 2, consumption: 1, ownHistory: null, ownLive: null, ownHistoryProduction: null, ownLiveProduction: null, forecast: 3, forecastBand: null }
        const { container } = await renderWithProviders(
            createElement(TodayChart, { date: '2026-10-30', rows: [row], through: null, hasLive: true }),
            cleanups,
        )

        expect(container.querySelector('h3')).toBeNull()
        expect(container.querySelector('.chart-card > p')).toBeNull()
        expect(container.querySelector('details')).toBeNull()
    })

})
