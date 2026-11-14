import { describe, expect, it } from 'vitest'
import { forecastTooltipLabel, kwTooltipText } from '../src/features/live/forecastChartParts'

describe('the forecast tooltip shared by the Today and Tomorrow charts', () => {
    it('writes a power as kW and a band as a range, never as a raw array', () => {
        expect(kwTooltipText(5.4)).toBe('5.4 kW')
        expect(kwTooltipText([3.8, 6.5])).toBe('3.8–6.5 kW')
        expect(kwTooltipText('n/a')).toBe('n/a')
    })

    it('names the day and the time in the Swiss time zone', () => {
        // 11:00 UTC is 12:00 in Zurich in winter.
        expect(forecastTooltipLabel(Date.parse('2026-11-15T11:00:00Z'))).toMatch(/15\.?.*12:00$/)
    })
})
