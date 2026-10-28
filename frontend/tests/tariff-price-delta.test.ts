import { describe, expect, it } from 'vitest'
import { deltaSummary, versionDeltas } from '../src/features/tariffs/priceDelta'
import type { TariffPeriod, TariffSeries, TariffVersion } from '../src/types/api'

const band = (id: string, price: string, overrides: Partial<TariffPeriod> = {}) => ({
    id, tariff: 'v', period_type: 'high', label: '', price_chf_per_kwh: price, percentage: null,
    time_from: '07:00', time_to: '21:00', weekdays: '', months: '', ...overrides,
}) as TariffPeriod
const version = (periods: TariffPeriod[], overrides: Partial<TariffVersion> = {}) =>
    ({ id: 'v', periods, dynamic_source: null, fixed_price_chf: null, ...overrides }) as unknown as TariffVersion
const series = (billing_mode: string) => ({ billing_mode }) as unknown as TariffSeries

describe('versionDeltas', () => {
    it('compares each band with the same band of the earlier version', () => {
        const from = version([band('a', '0.295'), band('b', '0.180', { period_type: 'low', time_from: '21:00', time_to: '07:00' })])
        const to = version([band('c', '0.315'), band('d', '0.180', { period_type: 'low', time_from: '21:00', time_to: '07:00' })])
        const { bands } = versionDeltas(series('energy'), from, to)
        expect(bands.get('c')).toEqual({ diff: 0.02, percent: 6.8, unit: 'price' })
        expect(bands.has('d')).toBe(false)
    })

    it('leaves out a band that is new, and compares percentage points for a percentage tariff', () => {
        const from = version([band('a', '0', { percentage: '60' })])
        const to = version([band('b', '0', { percentage: '65' }), band('c', '0', { percentage: '50', time_from: '00:00', time_to: '06:00' })])
        const { bands } = versionDeltas(series('percentage_of_energy'), from, to)
        expect(bands.get('b')).toEqual({ diff: 5, percent: null, unit: 'points' })
        expect(bands.has('c')).toBe(false)
    })

    it('compares the fixed fee of a flat-fee tariff, and nothing for a dynamic version', () => {
        const fee = (price: string) => version([], { fixed_price_chf: price })
        expect(versionDeltas(series('monthly_fee'), fee('10.00'), fee('12.00')).version).toEqual({ diff: 2, percent: 20, unit: 'chf' })
        expect(versionDeltas(series('monthly_fee'), fee('10.00'), fee('10.00')).version).toBeNull()
        const dynamic = version([], { dynamic_source: 's' as never })
        expect(versionDeltas(series('energy'), dynamic, version([band('a', '0.3')])).bands.size).toBe(0)
    })

    it('summarises the relative change of every price for the overview row', () => {
        const from = version([band('a', '0.200'), band('b', '0.100', { period_type: 'low' })])
        const to = version([band('c', '0.210'), band('d', '0.100', { period_type: 'low' })])
        const points = (diff: number) => `${diff} pts`
        expect(deltaSummary(series('energy'), from, to, points)).toBe('+5 % / \u00b10')
        expect(deltaSummary(series('energy'), from, from, points)).toBeNull()
    })
})
