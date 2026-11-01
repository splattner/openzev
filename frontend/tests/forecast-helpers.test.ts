import { describe, expect, it } from 'vitest'
import { forecastForDay, forecastRows, hasExpectedProduction, hasForecast, hoursOfDay, nextPeakWindow, peakDayKind, peakRange } from '../src/lib/forecast'
import { azimuthLabelKey, coordinateInput, planeInput } from '../src/lib/pvPlanes'
import { forecastEligible, sourceFor } from '../src/lib/supplementary'
import type { ForecastPeakWindow, ProductionForecast, SupplementarySource } from '../src/types/api'

const forecast = (overrides: Partial<ProductionForecast> = {}): ProductionForecast => ({
    zev_id: 'z1',
    horizon_h: 72,
    complete: true,
    plants: 1,
    plants_with_forecast: 1,
    fetched_at: '2026-06-01T08:00:00Z',
    hours: [{ start: '2026-06-01T10:00:00Z', power_w: 6400, min_w: 5000, max_w: 7000 }],
    peak_windows: [],
    ...overrides,
})

const window = (date: string, from: string, to: string): ForecastPeakWindow => ({ date, from, to, peak_w: 7900 })

describe('forecastRows', () => {
    it('turns watts into kW and keeps the band only when both ends are known', () => {
        const rows = forecastRows([
            { start: '2026-06-01T10:00:00Z', power_w: 6400, min_w: 5000, max_w: 7000 },
            { start: '2026-06-01T11:00:00Z', power_w: 500, min_w: null, max_w: null },
            { start: '2026-06-01T12:00:00Z', power_w: 100, min_w: 50, max_w: null },
        ])
        expect(rows.map((row) => row.power)).toEqual([6.4, 0.5, 0.1])
        expect(rows[0].band).toEqual([5, 7])
        expect(rows[1].band).toBeNull()
        expect(rows[2].band).toBeNull()
        expect(rows[0].ts).toBe(Date.parse('2026-06-01T10:00:00Z'))
    })
})

describe('hasForecast', () => {
    it('needs a plant with hours', () => {
        expect(hasForecast(forecast())).toBe(true)
        expect(hasForecast(forecast({ plants_with_forecast: 0 }))).toBe(false)
        expect(hasForecast(forecast({ hours: [] }))).toBe(false)
        expect(hasForecast(null)).toBe(false)
        expect(hasForecast(undefined)).toBe(false)
    })
})

describe('one civil day of a forecast', () => {
    // 22:00 UTC on 31 May is midnight in Zurich (summer time), so these two hours are on different civil days.
    const hours = [
        { start: '2026-05-31T21:00:00Z', power_w: 0, min_w: null, max_w: null },
        { start: '2026-05-31T22:00:00Z', power_w: 100, min_w: null, max_w: null },
        { start: '2026-06-01T10:00:00Z', power_w: 6400, min_w: 5000, max_w: 7000 },
    ]
    const full = forecast({
        hours,
        peak_windows: [window('2026-06-01', '2026-06-01T08:00:00Z', '2026-06-01T12:00:00Z'), window('2026-06-02', '2026-06-02T08:00:00Z', '2026-06-02T12:00:00Z')],
        per_plant: [{ metering_point_id: 'mp', meter_id: 'CH-1', hours }],
    })

    it('splits hours at Zurich midnight, not UTC midnight', () => {
        expect(hoursOfDay(hours, '2026-05-31').map((hour) => hour.start)).toEqual(['2026-05-31T21:00:00Z'])
        expect(hoursOfDay(hours, '2026-06-01').map((hour) => hour.start)).toEqual(['2026-05-31T22:00:00Z', '2026-06-01T10:00:00Z'])
    })

    it('narrows the hours and the peak window and drops the per-plant series', () => {
        const day = forecastForDay(full, '2026-06-01')
        expect(day.hours).toHaveLength(2)
        expect(day.peak_windows.map((w) => w.date)).toEqual(['2026-06-01'])
        expect(day.per_plant).toBeUndefined()
        expect(day.plants_with_forecast).toBe(1)
    })

    it('has expected production only when some hour of the day is above zero', () => {
        expect(hasExpectedProduction(full, '2026-06-01')).toBe(true)
        expect(hasExpectedProduction(full, '2026-05-31')).toBe(false)
        expect(hasExpectedProduction(full, '2026-06-03')).toBe(false)
        expect(hasExpectedProduction(null, '2026-06-01')).toBe(false)
    })
})

describe('peak windows', () => {
    const windows = [
        window('2026-06-01', '2026-06-01T08:00:00Z', '2026-06-01T12:00:00Z'),
        window('2026-06-02', '2026-06-02T08:00:00Z', '2026-06-02T12:00:00Z'),
    ]

    it('picks the one that is running or next', () => {
        expect(nextPeakWindow(windows, new Date('2026-06-01T09:00:00Z'))).toBe(windows[0])
        expect(nextPeakWindow(windows, new Date('2026-06-01T12:00:00Z'))).toBe(windows[1])
        expect(nextPeakWindow(windows, new Date('2026-06-03T00:00:00Z'))).toBeUndefined()
    })

    it('names today and tomorrow in the business time zone', () => {
        const now = new Date('2026-06-01T09:00:00Z')
        expect(peakDayKind(windows[0], now)).toBe('today')
        expect(peakDayKind(windows[1], now)).toBe('tomorrow')
        expect(peakDayKind(window('2026-06-05', '', ''), now)).toBe('date')
    })

    it('formats the range as local clock times', () => {
        // 08:00 to 12:00 UTC is 10:00 to 14:00 in Zurich in June.
        expect(peakRange(windows[0])).toBe('10:00–14:00')
    })
})

describe('planeInput', () => {
    const draft = { label: ' South ', kwp: '8.5', tilt: '30', azimuth: '-10' }

    it('parses a valid draft into the API input', () => {
        expect(planeInput(draft)).toEqual({ label: 'South', peak_power_kwp: '8.50', tilt_deg: 30, azimuth_deg: -10 })
    })

    it('rejects values the server would refuse', () => {
        for (const bad of [{ kwp: '' }, { kwp: '0' }, { kwp: '10001' }, { tilt: '91' }, { tilt: '-1' }, { tilt: '1.5' }, { azimuth: '181' }, { azimuth: '' }, { kwp: 'x' }]) {
            expect(planeInput({ ...draft, ...bad }), JSON.stringify(bad)).toBeNull()
        }
    })
})

describe('azimuthLabelKey', () => {
    it('maps the forecast.solar convention (0 south, 90 west, -90 east) to a direction', () => {
        const direction = (azimuth: number) => azimuthLabelKey(azimuth).split('.').pop()
        expect(direction(0)).toBe('south')
        expect(direction(-90)).toBe('east')
        expect(direction(90)).toBe('west')
        expect(direction(180)).toBe('north')
        expect(direction(-180)).toBe('north')
        expect(direction(45)).toBe('southWest')
        expect(direction(-45)).toBe('southEast')
        expect(direction(135)).toBe('northWest')
        expect(direction(-135)).toBe('northEast')
        expect(direction(-10)).toBe('south')
    })
})

describe('coordinateInput', () => {
    it('gives five decimals, accepts a decimal comma and treats empty as none', () => {
        expect(coordinateInput('47,37691', 90)).toBe('47.37691')
        expect(coordinateInput(' 8.5 ', 180)).toBe('8.50000')
        expect(coordinateInput('', 90)).toBeNull()
    })

    it('rejects what is not a coordinate', () => {
        expect(coordinateInput('91', 90)).toBeUndefined()
        expect(coordinateInput('-181', 180)).toBeUndefined()
        expect(coordinateInput('north', 90)).toBeUndefined()
    })
})

describe('forecast capability in the source helpers', () => {
    const source = (overrides: Partial<SupplementarySource>) =>
        ({ metering_point: 'mp1', target: 'metering_point', zev: 'z1', provides_history: false, provides_live: false, provides_forecast: false, ...overrides }) as SupplementarySource

    it('finds the source that provides a forecast', () => {
        const sources = [source({ provides_history: true }), source({ provides_forecast: true, provider: 'forecast_solar' })]
        expect(sourceFor(sources, 'mp1', 'forecast')).toBe(sources[1])
        expect(sourceFor(sources, 'mp1', 'history')).toBe(sources[0])
        expect(sourceFor(sources, 'mp2', 'forecast')).toBeUndefined()
    })

    it('reads forecast eligibility from the capabilities of the point', () => {
        expect(forecastEligible({ eligible_capabilities: ['live', 'forecast'] })).toBe(true)
        expect(forecastEligible({ eligible_capabilities: ['history', 'live'] })).toBe(false)
        expect(forecastEligible({})).toBe(false)
    })
})
