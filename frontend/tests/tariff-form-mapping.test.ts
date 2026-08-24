import { describe, expect, it } from 'vitest'
import {
  defaultTariffFormValues,
  defaultTariffPeriodFormValues,
  mapTariffFormValuesToInput,
  mapTariffPeriodFormValuesToInput,
  mapTariffPeriodToFormValues,
  mapTariffToFormValues,
} from '../src/features/tariffs/useTariffForms'
import type { Tariff, TariffPeriod } from '../src/types/api'

describe('tariff form mapping', () => {
  it('maps tariff api model into form values', () => {
    const tariff = {
      id: 't-1',
      zev: 'z-1',
      name: 'Energy 2026',
      category: 'energy',
      billing_mode: 'percentage_of_energy',
      energy_type: 'grid',
      fixed_price_chf: null,
      percentage: '12.50',
      valid_from: '2026-01-01',
      valid_to: null,
      notes: null,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    } as unknown as Tariff

    expect(mapTariffToFormValues(tariff)).toEqual({
      ...defaultTariffFormValues,
      name: 'Energy 2026',
      billing_mode: 'percentage_of_energy',
      energy_type: 'grid',
      percentage: '12.50',
      valid_from: '2026-01-01',
    })
  })

  it('maps tariff form values into energy payload', () => {
    const payload = mapTariffFormValuesToInput(
      {
        ...defaultTariffFormValues,
        name: 'Energy Local',
        billing_mode: 'energy',
        energy_type: 'local',
        fixed_price_chf: '',
        percentage: '',
      },
      'z-1',
    )

    expect(payload).toEqual({
      zev: 'z-1',
      name: 'Energy Local',
      category: 'energy',
      billing_mode: 'energy',
      energy_type: 'local',
      fixed_price_chf: null,
      percentage: null,
      // Not a shared fee mode, so split_key is forced to 'equal' regardless
      // of the form value — it only means something for SHARED_* tariffs.
      split_key: 'equal',
      valid_from: defaultTariffFormValues.valid_from,
      valid_to: null,
      notes: '',
    })
  })

  it('preserves split_key for a shared fee, and ignores it for a non-shared one', () => {
    const shared = mapTariffFormValuesToInput(
      { ...defaultTariffFormValues, billing_mode: 'shared_monthly_fee', fixed_price_chf: '90.00', split_key: 'weight' },
      'z-1',
    )
    expect(shared.split_key).toBe('weight')

    const nonShared = mapTariffFormValuesToInput(
      { ...defaultTariffFormValues, billing_mode: 'monthly_fee', fixed_price_chf: '10.00', split_key: 'weight' },
      'z-1',
    )
    expect(nonShared.split_key).toBe('equal')
  })

  it('maps tariff period api model and form values correctly', () => {
    const period = {
      id: 'tp-1',
      tariff: 't-1',
      period_type: 'high',
      price_chf_per_kwh: '0.45',
      time_from: '06:00',
      time_to: '22:00',
      weekdays: '1,2,3,4,5',
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    } as unknown as TariffPeriod

    expect(mapTariffPeriodToFormValues(period)).toEqual({
      ...defaultTariffPeriodFormValues,
      tariff: 't-1',
      period_type: 'high',
      price_chf_per_kwh: '0.45',
      time_from: '06:00',
      time_to: '22:00',
      weekdays: '1,2,3,4,5',
    })

    expect(
      mapTariffPeriodFormValuesToInput({
        tariff: 't-1',
        period_type: 'low',
        price_chf_per_kwh: '0.12',
        time_from: '',
        time_to: '',
        weekdays: '',
      }),
    ).toEqual({
      tariff: 't-1',
      period_type: 'low',
      price_chf_per_kwh: '0.12',
      time_from: null,
      time_to: null,
      weekdays: '',
    })
  })
})
