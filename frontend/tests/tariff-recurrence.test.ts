import { describe, it, expect } from 'vitest'
import {
    MONTH_KEYS,
    WEEKDAY_KEYS,
    formatSeason,
    monthRanges,
    parseMonths,
    recurrenceValue,
    seasonSortKey,
    selectedRecurrence,
} from '../src/features/tariffs/recurrence'
import { buildPriceHistory } from '../src/features/tariffs/priceHistory'
import type { TariffSeries, TariffVersion } from '../src/types/api'

/**
 * Seasonal bands (#527). These mirror `backend/tariffs/periods.py`, and the two
 * have to agree: one writes the season on the contract PDF, the other on
 * screen, and a participant comparing them should not find two answers.
 */
const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

describe('parsing a month mask', () => {
    it('reads a stored mask in numeric order', () => {
        expect(parseMonths('10,11,12,1,2,3')).toEqual([1, 2, 3, 10, 11, 12])
    })

    it('treats blank and undefined as no restriction', () => {
        expect(parseMonths('')).toEqual([])
        expect(parseMonths(undefined)).toEqual([])
    })

    it('drops anything outside 1-12 rather than charting it', () => {
        expect(parseMonths('0,5,13,abc')).toEqual([5])
    })

    it('names all twelve months in calendar order', () => {
        expect(MONTH_KEYS).toHaveLength(12)
        expect(MONTH_KEYS[0]).toBe('jan')
        expect(MONTH_KEYS[11]).toBe('dec')
    })
})

const WEEKDAY_VALUES = [0, 1, 2, 3, 4, 5, 6]
const MONTH_VALUES = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]

describe('the weekday and month toggle groups', () => {
    it('names all seven weekdays, Monday first', () => {
        // 0 = Monday, matching Date#getDay() shifted and the backend's mask.
        expect(WEEKDAY_KEYS).toHaveLength(7)
        expect(WEEKDAY_KEYS[0]).toBe('mon')
        expect(WEEKDAY_KEYS[6]).toBe('sun')
    })

    it('shows every option lit for an unrestricted band', () => {
        // Blank means "no restriction". Rendering that as nothing selected
        // would make turning one off read as "now only this one".
        expect(selectedRecurrence('', WEEKDAY_VALUES)).toEqual(['0', '1', '2', '3', '4', '5', '6'])
        expect(selectedRecurrence(undefined, MONTH_VALUES)).toHaveLength(12)
    })

    it('shows exactly what a restricted band stored', () => {
        expect(selectedRecurrence('0,1,2,3,4', WEEKDAY_VALUES)).toEqual(['0', '1', '2', '3', '4'])
    })

    it('stores nothing when everything is selected', () => {
        // So a band that applies always looks the same however it was reached.
        expect(recurrenceValue(['0', '1', '2', '3', '4', '5', '6'], 7)).toBe('')
    })

    it('stores a restricted selection in numeric order', () => {
        expect(recurrenceValue(['10', '1', '2'], 12)).toBe('1,2,10')
    })

    it('refuses a selection of nothing', () => {
        // A band applying on no day at all cannot be stored, and would not
        // mean anything if it could — so the click is a no-op.
        expect(recurrenceValue([], 7)).toBeNull()
    })
})

describe('naming a season', () => {
    it('reads a winter season as one range across the new year', () => {
        // "Jan–Mar, Oct–Dec" makes the reader work out that it is one season.
        expect(formatSeason('10,11,12,1,2,3', MONTH_NAMES)).toBe('Oct–Mar')
    })

    it('reads a summer season as one range', () => {
        expect(formatSeason('4,5,6,7,8,9', MONTH_NAMES)).toBe('Apr–Sep')
    })

    it('has nothing to name for a band that applies all year', () => {
        expect(formatSeason('', MONTH_NAMES)).toBe('')
        expect(formatSeason('1,2,3,4,5,6,7,8,9,10,11,12', MONTH_NAMES)).toBe('')
    })

    it('keeps genuinely disjoint stretches apart', () => {
        expect(monthRanges([1, 2, 6, 7, 12])).toEqual([[6, 7], [12, 2]])
    })

    it('names a single month without a range', () => {
        expect(formatSeason('7', MONTH_NAMES)).toBe('Jul')
    })
})

describe('ordering bands for display', () => {
    it('puts year-round bands before seasonal ones', () => {
        expect(seasonSortKey('')).toBeLessThan(seasonSortKey('4,5,6'))
    })

    it('orders seasons by the month they start in', () => {
        expect(seasonSortKey('4,5,6,7,8,9')).toBeLessThan(seasonSortKey('10,11,12,1,2,3'))
    })
})

/**
 * The price-history chart used to pick the first band matching a type, which
 * for a seasonal tariff charted one season's price as if it applied all year.
 */
function version(periods: TariffVersion['periods'], overrides: Partial<TariffVersion> = {}): TariffVersion {
    return {
        id: 'v1', zev: 'z1', name: 'Grid', category: 'grid_fees', billing_mode: 'energy',
        energy_type: 'grid', fixed_price_chf: null, percentage: null, split_key: 'equal',
        valid_from: '2026-01-01', valid_to: '2026-12-31', notes: '',
        periods, ...overrides,
    } as TariffVersion
}

function series(versions: TariffVersion[]): TariffSeries {
    return {
        zev: 'z1', name: 'Grid', category: 'grid_fees', billing_mode: 'energy',
        energy_type: 'grid', version_count: versions.length,
        active_version_id: versions[0].id, gaps: [], versions,
    } as TariffSeries
}

function band(id: string, price: string, months: string) {
    return {
        id, tariff: 'v1', period_type: 'flat' as const,
        price_chf_per_kwh: price, time_from: null, time_to: null, weekdays: '', months,
    }
}

describe('charting a seasonal tariff', () => {
    it('steps between the seasons instead of drawing one of them all year', () => {
        const history = buildPriceHistory(
            series([version([band('w', '0.25', '1,2,3,10,11,12'), band('s', '0.15', '4,5,6,7,8,9')])]),
            [],
            '2026-06-15',
        )

        const priced = history.points.filter((point) => point.values.flat != null)

        // Winter until end of March, summer April to September, winter again.
        expect(priced[0]).toMatchObject({ date: '2026-01-01', values: { flat: 0.25 } })
        expect(priced.some((p) => p.date === '2026-04-01' && p.values.flat === 0.15)).toBe(true)
        expect(priced.some((p) => p.date === '2026-10-01' && p.values.flat === 0.25)).toBe(true)
    })

    it('leaves a year-round tariff charted exactly as before', () => {
        const history = buildPriceHistory(
            series([version([band('f', '0.20', '')])]),
            [],
            '2026-06-15',
        )

        expect(history.points).toHaveLength(2)
        expect(history.points.every((point) => point.values.flat === 0.2)).toBe(true)
    })
})
