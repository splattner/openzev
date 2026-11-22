import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { expect, it } from 'vitest'
import { bandCoverage } from '../src/features/tariffs/bandCoverage'

const scenarios: Array<{
    name: string
    bands: Parameters<typeof bandCoverage>[0]
    samples: Array<{ at: string, band_id: string, covered: boolean }>
}> = JSON.parse(readFileSync(resolve(__dirname, '../../backend/tariffs/testdata/band-resolution.json'), 'utf8'))

it.each(scenarios)('reports gaps and fallback bands: $name', ({ bands, samples }) => {
    const { gaps, fallbacks } = bandCoverage(bands)
    for (const sample of samples) {
        // `at` is a Swiss wall clock: read it as UTC so the runner's timezone cannot shift it.
        const at = new Date(`${sample.at}Z`)
        const month = at.getUTCMonth() + 1
        const weekday = (at.getUTCDay() + 6) % 7
        const seconds = at.getUTCHours() * 3600 + at.getUTCMinutes() * 60 + at.getUTCSeconds()
        const uncovered = gaps.some(gap => gap.months.includes(month) && gap.weekdays.includes(weekday)
            && gap.start <= seconds && seconds < gap.end)
        expect(uncovered, sample.at).toBe(!sample.covered)
        if (uncovered) expect(fallbacks.find(entry => entry.months.includes(month))?.band.id, sample.at).toBe(sample.band_id)
    }
})
