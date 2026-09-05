import { describe, it, expect } from 'vitest'
import { tariffOverviewFilename, tariffOverviewParams } from '../src/features/tariffs/tariffOverview'

describe('tariffOverviewParams', () => {
    it('maps the "valid" validity filter to scope=valid', () => {
        expect(tariffOverviewParams('zev-1', 'valid')).toEqual({ zev_id: 'zev-1', scope: 'valid' })
    })

    it('maps the "all" validity filter to scope=all', () => {
        expect(tariffOverviewParams('zev-1', 'all')).toEqual({ zev_id: 'zev-1', scope: 'all' })
    })
})

describe('tariffOverviewFilename', () => {
    it('names the file after the as-of date', () => {
        expect(tariffOverviewFilename('2026-09-05')).toBe('tariff-overview-2026-09-05.pdf')
    })
})
