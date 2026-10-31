import { describe, expect, it } from 'vitest'
import {
    formatClock,
    formatKw,
    kwFigure,
    liveCardState,
    liveCurveRows,
    liveDayAxis,
    liveSnapshotRefetchInterval,
    showLiveCard,
} from '../src/lib/live'
import type { LiveSnapshot } from '../src/types/api'

const snapshot = (overrides: Partial<LiveSnapshot> = {}, liveSources = 2): LiveSnapshot => ({
    zev_id: 'z1',
    as_of: '2026-10-30T11:02:10Z',
    tier: 'exact',
    consumption_basis: 'all_points',
    production_w: 8000,
    consumption_w: 5000,
    surplus_w: 3000,
    grid_import_w: 0,
    local_share_pct: 100,
    coverage: { producing_points: 1, producing_fresh: 1, consuming_points: 2, consuming_fresh: 2, connection_point: null, live_sources: liveSources },
    own: null,
    max_age_s: 60,
    ...overrides,
})

describe('formatKw', () => {
    it('shows kW with one decimal and a no-break space', () => {
        expect(formatKw(1234)).toBe('1.2\u00a0kW')
        expect(formatKw(0)).toBe('0.0\u00a0kW')
        expect(formatKw(8000)).toBe('8.0\u00a0kW')
        expect(kwFigure(49)).toBe('0.0')
    })

    it('shows a dash for a number that is not finite', () => {
        expect(formatKw(Number.NaN)).toBe('–')
    })
})

describe('formatClock', () => {
    it('shows hh:mm:ss in the business timezone', () => {
        expect(formatClock('2026-10-30T11:02:10Z')).toBe('12:02:10')
        expect(formatClock('2026-12-01T23:30:05Z')).toBe('00:30:05')
    })
})

describe('showLiveCard', () => {
    it('is hidden without an answer or without a live source', () => {
        expect(showLiveCard(null)).toBe(false)
        expect(showLiveCard(undefined)).toBe(false)
        expect(showLiveCard(snapshot({}, 0))).toBe(false)
        expect(showLiveCard(snapshot({}, 1))).toBe(true)
    })
})

describe('liveCardState', () => {
    it('is null while the card is hidden', () => {
        expect(liveCardState(null)).toBeNull()
        expect(liveCardState(snapshot({}, 0))).toBeNull()
    })

    it('knows only the production below exact and never a split', () => {
        const own = { consumption_w: 1200, local_w: 1200, grid_w: 0, production_w: null, to_zev_w: null, to_grid_w: null, gross: { production_w: null, consumption_w: null }, complete: true, points: 1, points_fresh: 1 }
        const state = liveCardState(snapshot({ tier: 'production', own }))

        expect(state).toMatchObject({ showProduction: true, showExact: false, ownConsumption: true, ownSplit: 'none' })
    })

    it('has nothing at tier none, not even the own figures', () => {
        const state = liveCardState(snapshot({ tier: 'none', production_w: null, own: { consumption_w: 1, local_w: null, grid_w: null, production_w: null, to_zev_w: null, to_grid_w: null, gross: { production_w: null, consumption_w: null }, complete: true, points: 1, points_fresh: 1 } }))

        expect(state).toMatchObject({ showProduction: false, showExact: false, ownConsumption: false })
    })

    it('marks the detailed view by the presence of the points', () => {
        expect(liveCardState(snapshot())?.detailed).toBe(false)
        expect(liveCardState(snapshot({ points: [] }))?.detailed).toBe(true)
    })
})

describe('liveSnapshotRefetchInterval', () => {
    it('polls every 15 s while there is an answer or none yet', () => {
        expect(liveSnapshotRefetchInterval({ state: { data: snapshot() } })).toBe(15_000)
        expect(liveSnapshotRefetchInterval({ state: { data: undefined } })).toBe(15_000)
    })

    it('stops for good once the server answered 404 (null)', () => {
        expect(liveSnapshotRefetchInterval({ state: { data: null } })).toBe(false)
    })
})

describe('liveCurveRows', () => {
    const rows = liveCurveRows([
        { start: '2026-10-30T08:00:00Z', tier: 'exact', production_w: 8000, consumption_w: 5000, surplus_w: 3000, own_consumption_w: 1200 },
        { start: '2026-10-30T08:05:00Z', tier: 'none' },
        { start: '2026-10-30T08:10:00Z', tier: 'production', production_w: 7500, own_consumption_w: null },
    ])

    it('converts W to kW', () => {
        expect(rows[0]).toEqual({ ts: Date.parse('2026-10-30T08:00:00Z'), production: 8, consumption: 5, own: 1.2 })
    })

    it('leaves a none bucket as a gap in every series', () => {
        expect(rows[1]).toEqual({ ts: Date.parse('2026-10-30T08:05:00Z'), production: null, consumption: null, own: null })
    })

    it('has no consumption below exact and no own value that was not sent', () => {
        expect(rows[2]).toEqual({ ts: Date.parse('2026-10-30T08:10:00Z'), production: 7.5, consumption: null, own: null })
    })

    it('never drops the production of a production bucket even if consumption was sent', () => {
        const row = liveCurveRows([{ start: '2026-10-30T08:00:00Z', tier: 'production', production_w: 1000, consumption_w: 999 }])[0]
        expect(row.consumption).toBeNull()
    })
})

describe('liveDayAxis', () => {
    it('spans the civil day with a tick every three hours', () => {
        const axis = liveDayAxis('2026-10-30')
        expect(axis.end - axis.start).toBe(24 * 3_600_000)
        expect(axis.ticks).toHaveLength(9)
        expect(axis.start).toBe(Date.parse('2026-10-29T23:00:00Z'))
    })

    it('follows the 25-hour day of the clock change', () => {
        const axis = liveDayAxis('2026-10-25')
        expect(axis.end - axis.start).toBe(25 * 3_600_000)
    })
})
