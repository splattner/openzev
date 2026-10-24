import { describe, expect, it } from 'vitest'
import { resolvePeriodTariffId } from '../src/features/tariffs/useTariffCrud'
import type { Tariff } from '../src/types/api'

describe('resolvePeriodTariffId', () => {
  it('returns explicitly provided tariff id', () => {
    const energyTariffs = [{ id: 'energy-1' } as unknown as Tariff]

    expect(resolvePeriodTariffId(energyTariffs, 'manual-1')).toBe('manual-1')
  })

  it('returns first energy tariff id when no explicit id is given', () => {
    const energyTariffs = [{ id: 'energy-1' } as unknown as Tariff, { id: 'energy-2' } as unknown as Tariff]

    expect(resolvePeriodTariffId(energyTariffs)).toBe('energy-1')
  })

  it('returns undefined when no energy tariff exists', () => {
    expect(resolvePeriodTariffId([])).toBeUndefined()
  })
})
