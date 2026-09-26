import { describe, expect, it } from 'vitest'
import { percentageRangeLabel, percentageValues } from '../src/features/tariffs/useTariffDisplay'
import type { TariffPeriod, TariffVersion } from '../src/types/api'

// SPEC-2026-percentage-tariff-bands §5.7: the series summary and its
// effective-price tooltip use one percentage when every band shares it,
// otherwise a min-max range, and fall back to "no bands" text.

function pctPeriod(percentage: string | null): TariffPeriod {
  return { id: `p-${percentage}`, tariff: 't', period_type: 'flat', price_chf_per_kwh: null, percentage }
}

function version(periods: TariffPeriod[]): TariffVersion {
  return {
    id: 'v1', zev: 'z1', name: 'Local', category: 'energy', billing_mode: 'percentage_of_energy',
    energy_type: 'local', valid_from: '2026-01-01', valid_to: null, periods,
  } as TariffVersion
}

describe('percentageValues', () => {
  it('reads every band percentage as a number', () => {
    expect(percentageValues(version([pctPeriod('60.00'), pctPeriod('90.00')]))).toEqual([60, 90])
  })

  it('is empty for a tariff with no bands yet', () => {
    expect(percentageValues(version([]))).toEqual([])
  })
})

describe('percentageRangeLabel', () => {
  it('is null without bands, so the caller can fall back to its own noPeriods text', () => {
    expect(percentageRangeLabel([])).toBeNull()
  })

  it('is a single percentage when every band shares one', () => {
    expect(percentageRangeLabel([60, 60, 60])).toBe('60%')
  })

  it('is a min-max range when bands differ', () => {
    expect(percentageRangeLabel([60, 90])).toBe('60–90%')
  })

  it('orders the range low to high regardless of input order', () => {
    expect(percentageRangeLabel([90, 60, 75])).toBe('60–90%')
  })
})
