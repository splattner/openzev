import { describe, expect, it } from 'vitest'
import { bandCoverage, type CoverageBand } from '../src/features/tariffs/bandCoverage'
import { nextChange } from '../src/features/tariffs/rateLines'

// Mirrors tariffs.periods.resolve_band: what the engine prices, and what it leaves to the fallback.

const flat = (extra: Partial<CoverageBand> = {}): CoverageBand => ({ period_type: 'flat', price_chf_per_kwh: '0.20', ...extra })
const high = (extra: Partial<CoverageBand> = {}): CoverageBand => ({ period_type: 'high', time_from: '07:00:00', time_to: '21:00:00', price_chf_per_kwh: '0.30', ...extra })
const low = (extra: Partial<CoverageBand> = {}): CoverageBand => ({ period_type: 'low', time_from: '21:00:00', time_to: '07:00:00', price_chf_per_kwh: '0.20', ...extra })
const HOUR = 3600

describe('bandCoverage', () => {
    it('lets a band without a window price every hour the windowed bands leave open', () => {
        const coverage = bandCoverage([high({ weekdays: '0,1,2,3,4' }), low({ time_from: null, time_to: null })])
        expect(coverage.uncovered).toBe(false)
        expect(coverage.gaps).toEqual([])
        expect(coverage.fallbacks).toEqual([])
        expect(coverage.overlaps).toBe(false)
    })

    it('leaves the other days as gaps when the catch-all is restricted to some weekdays', () => {
        const coverage = bandCoverage([high({ weekdays: '0,1,2,3,4' }), low({ time_from: null, time_to: null, weekdays: '5,6' })])
        expect(coverage.gaps).toHaveLength(2)
        expect(coverage.gaps.map(({ start, end }) => [start / HOUR, end / HOUR])).toEqual([[0, 7], [21, 24]])
        expect(coverage.gaps.every((gap) => gap.weekdays.join() === '0,1,2,3,4')).toBe(true)
    })

    it('reports two catch-alls on the same month and day as an overlap', () => {
        const rest = (extra: Partial<CoverageBand> = {}) => low({ time_from: null, time_to: null, ...extra })
        expect(bandCoverage([high(), rest(), rest({ period_type: 'band' })]).overlaps).toBe(true)
        expect(bandCoverage([high(), rest({ months: '1,2' }), rest({ period_type: 'band', months: '3' })]).overlaps).toBe(false)
    })

    it('finds nothing wrong with a flat band, or with high and low that complete the day', () => {
        expect(bandCoverage([flat()]).uncovered).toBe(false)
        const both = bandCoverage([high(), low()])
        expect(both.uncovered).toBe(false)
        expect(both.overlaps).toBe(false)
    })

    it('reads an end of 00:00 as the end of the day and equal ends as the whole day', () => {
        expect(bandCoverage([high({ time_to: '00:00:00' }), low({ time_from: '00:00:00', time_to: '07:00:00' })]).uncovered).toBe(false)
        expect(bandCoverage([high({ time_from: '00:00:00', time_to: '00:00:00' })]).uncovered).toBe(false)
    })

    it('names the hours a lone high band leaves open, and the band that prices them', () => {
        const only = high({ id: 'a' })
        const coverage = bandCoverage([only])
        expect(coverage.uncovered).toBe(true)
        expect(coverage.gaps).toHaveLength(2)
        expect(coverage.gaps.map(({ start, end }) => [start / HOUR, end / HOUR])).toEqual([[0, 7], [21, 24]])
        expect(coverage.gaps.every((gap) => gap.months.length === 12 && gap.weekdays.length === 7)).toBe(true)
        expect(coverage.fallbacks).toEqual([{ band: only, months: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12] }])
    })

    it('finds the weekend a Monday to Friday band leaves open', () => {
        const coverage = bandCoverage([high({ weekdays: '0,1,2,3,4' }), low()])
        expect(coverage.gaps).toHaveLength(1)
        expect(coverage.gaps[0]).toMatchObject({ weekdays: [5, 6], start: 7 * HOUR, end: 21 * HOUR })
    })

    it('finds the months nothing prices, and falls back to the first band overall there', () => {
        const winter = flat({ id: 'w', months: '11,12,1,2' })
        const coverage = bandCoverage([winter])
        expect(coverage.uncovered).toBe(true)
        expect(coverage.gaps).toHaveLength(1)
        expect(coverage.gaps[0].months).toEqual([3, 4, 5, 6, 7, 8, 9, 10])
        expect(coverage.fallbacks[0].band).toBe(winter)
    })

    it('does not count winter-flat with summer high and low as a problem', () => {
        const coverage = bandCoverage([flat({ months: '11,12,1,2,3' }), high({ months: '4,5,6,7,8,9,10' }), low({ months: '4,5,6,7,8,9,10' })])
        expect(coverage.uncovered).toBe(false)
        expect(coverage.overlaps).toBe(false)
    })

    it('reports bands that match the same hour; the first one prices it', () => {
        expect(bandCoverage([high(), high({ id: 'b', time_from: '12:00:00', time_to: '14:00:00' }), low()]).overlaps).toBe(true)
    })

    it('treats a band with only one end like the engine does: as a band without a window', () => {
        // high loses its window and prices what low (21:00-07:00) leaves open.
        const coverage = bandCoverage([high({ time_to: null }), low()])
        expect(coverage.uncovered).toBe(false)
        expect(coverage.overlaps).toBe(false)
    })

    it('only checks the weekdays and months a short version can meet', () => {
        const weekdaysOnly = [high({ weekdays: '0,1,2,3,4' }), low({ weekdays: '0,1,2,3,4' })]
        expect(bandCoverage(weekdaysOnly).uncovered).toBe(true)
        // 2026-11-02 is a Monday, 2026-11-06 a Friday.
        expect(bandCoverage(weekdaysOnly, { valid_from: '2026-11-02', valid_to: '2026-11-06' }).uncovered).toBe(false)
        // An open-ended version is checked against the whole year.
        expect(bandCoverage(weekdaysOnly, { valid_from: '2026-11-02', valid_to: null }).uncovered).toBe(true)
    })

    it('has nothing to say about a version with no bands at all', () => {
        expect(bandCoverage([]).fallbacks).toEqual([])
    })
})

describe('nextChange', () => {
    const line = (applies: string, price: string, unit = 'CHF/kWh') => ({ applies, price, unit })

    it('shows the new prices when the same bands are repriced', () => {
        expect(nextChange(
            [line('High 07:00–21:00', '0.295'), line('Low 21:00–07:00', '0.225')],
            [line('High 07:00–21:00', '0.290'), line('Low 21:00–07:00', '0.220')],
        )).toEqual({ kind: 'prices', prices: '0.290 / 0.220', unit: 'CHF/kWh' })
    })

    it('says the schedule changes when the bands differ', () => {
        expect(nextChange([line('All hours', '0.18')], [line('High 07:00–21:00', '0.2'), line('Low 21:00–07:00', '0.1')])).toEqual({ kind: 'schedule' })
        expect(nextChange([line('High 07:00–21:00', '0.2')], [line('High 08:00–21:00', '0.2')])).toEqual({ kind: 'schedule' })
    })

    it('says only that a version follows when it has no prices to show', () => {
        expect(nextChange([line('All hours', '0.18')], [line('Dynamic', '—')])).toEqual({ kind: 'version' })
        expect(nextChange([line('All hours', '0.18')], [line('No bands', '', '')])).toEqual({ kind: 'version' })
    })
})
