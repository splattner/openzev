import { describe, it, expect } from 'vitest'
import { bandName, bandWindow } from '../src/features/tariffs/bands'
import { buildPriceHistory } from '../src/features/tariffs/priceHistory'
import type { TariffSeries, TariffVersion } from '../src/types/api'

/**
 * Tariffs with more than two priced bands (#528).
 *
 * `flat`, `high` and `low` are names; `band` is not. Everything here is about
 * what an unnamed band is called and how several of them reach the chart,
 * because those are the two places a third band used to vanish silently.
 */
describe('naming a band', () => {
    it('leaves the named types to their own names', () => {
        expect(bandName({ period_type: 'high' }, 'High tariff (HT)')).toBe('High tariff (HT)')
        expect(bandName({ period_type: 'flat' }, 'Flat')).toBe('Flat')
    })

    it('uses a band’s label when it has one', () => {
        expect(bandName(
            { period_type: 'band', label: 'Spitzenlast', time_from: '07:00:00', time_to: '17:00:00' },
            'Time band',
        )).toBe('Spitzenlast')
    })

    it('falls back to the window, which always tells bands apart', () => {
        expect(bandName(
            { period_type: 'band', time_from: '07:00:00', time_to: '17:00:00' },
            'Time band',
        )).toBe('07:00–17:00')
    })

    it('falls back to the type name when a band has neither', () => {
        expect(bandName({ period_type: 'band' }, 'Time band')).toBe('Time band')
    })

    it('reads a window from either time representation', () => {
        expect(bandWindow({ period_type: 'band', time_from: '07:00', time_to: '17:00' })).toBe('07:00–17:00')
        expect(bandWindow({ period_type: 'band', time_from: null, time_to: null })).toBeNull()
    })
})

function version(periods: TariffVersion['periods']): TariffVersion {
    return {
        id: 'v1', zev: 'z1', name: 'Grid', category: 'grid_fees', billing_mode: 'energy',
        energy_type: 'grid', fixed_price_chf: null, percentage: null, split_key: 'equal',
        valid_from: '2026-01-01', valid_to: '2026-12-31', notes: '', periods,
    } as TariffVersion
}

function series(versions: TariffVersion[]): TariffSeries {
    return {
        zev: 'z1', name: 'Grid', category: 'grid_fees', billing_mode: 'energy',
        energy_type: 'grid', version_count: versions.length,
        active_version_id: versions[0].id, gaps: [], versions,
    } as TariffSeries
}

function band(id: string, price: string, from: string, to: string, extra = {}) {
    return {
        id, tariff: 'v1', period_type: 'band' as const, price_chf_per_kwh: price,
        time_from: from, time_to: to, weekdays: '', months: '', label: '', ...extra,
    }
}

describe('charting a tariff with three bands', () => {
    const history = () => buildPriceHistory(
        series([version([
            band('a', '0.09', '00:00:00', '07:00:00'),
            band('b', '0.24', '07:00:00', '17:00:00', { label: 'Spitzenlast' }),
            band('c', '0.15', '17:00:00', '23:59:00'),
        ])]),
        [],
        '2026-06-15',
    )

    it('gives every band a series of its own', () => {
        // The chart used to look bands up by name, so a third one was simply
        // absent from the picture.
        expect(history().bands).toEqual(['band-0', 'band-1', 'band-2'])
    })

    it('labels each series by its label, else by its window', () => {
        expect(history().bandLabels).toEqual({
            'band-0': '00:00–07:00',
            'band-1': 'Spitzenlast',
            'band-2': '17:00–23:59',
        })
    })

    it('carries each band’s own price', () => {
        const first = history().points[0].values

        expect(first['band-0']).toBe(0.09)
        expect(first['band-1']).toBe(0.24)
        expect(first['band-2']).toBe(0.15)
    })

    it('keys bands by position, so a line follows the same band across versions', () => {
        // Positions are meaningful because the backend orders bands by start
        // time — `band-0` is the same band of the day in every version.
        expect(history().bands[0]).toBe('band-0')
    })
})

describe('charting the shapes that already worked', () => {
    it('still names an HT/NT tariff by its bands', () => {
        const history = buildPriceHistory(
            series([version([
                { ...band('h', '0.24', '07:00:00', '22:00:00'), period_type: 'high' as const },
                { ...band('l', '0.15', '22:00:00', '23:59:00'), period_type: 'low' as const },
            ])]),
            [],
            '2026-06-15',
        )

        expect(history.bands).toEqual(['high', 'low'])
        expect(history.bandLabels).toEqual({})
    })

    it('still charts a flat tariff as one line', () => {
        const history = buildPriceHistory(
            series([version([
                { ...band('f', '0.20', '00:00:00', '00:00:00'), period_type: 'flat' as const,
                  time_from: null, time_to: null },
            ])]),
            [],
            '2026-06-15',
        )

        expect(history.bands).toEqual(['flat'])
    })
})
