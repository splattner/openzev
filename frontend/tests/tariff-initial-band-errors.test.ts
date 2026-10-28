import { AxiosError } from 'axios'
import { describe, expect, it } from 'vitest'
import { formatApiErrorRest, splitIndexedErrors } from '../src/lib/api/errors'
import { tariffBandDraftSchema, defaultTariffPeriodFormValues } from '../src/features/tariffs/useTariffForms'

function badRequest(data: unknown) {
  return new AxiosError('Request failed', 'ERR_BAD_REQUEST', undefined, undefined, {
    status: 400, statusText: 'Bad Request', headers: {}, config: {} as never, data,
  })
}

describe('indexed errors of initial bands', () => {
  it('keeps each band error at the position of the band it names', () => {
    const { items, rest } = splitIndexedErrors(
      badRequest({ initial_periods: [{}, { price_chf_per_kwh: ['A price band needs a price.'] }, { non_field_errors: ['No.'] }] }),
      'initial_periods',
    )

    expect(items).toEqual([{}, { price_chf_per_kwh: ['A price band needs a price.'] }, { non_field_errors: ['No.'] }])
    expect(rest).toEqual({})
  })

  it('leaves the other fields of the response as the remaining message', () => {
    const { items, rest } = splitIndexedErrors(
      badRequest({ name: ['Required.'], initial_periods: [{ time_to: ['Both times.'] }] }),
      'initial_periods',
    )

    expect(items).toEqual([{ time_to: ['Both times.'] }])
    expect(formatApiErrorRest(rest, 'fallback')).toContain('name: Required')
  })

  it('says the fallback when nothing else is left', () => {
    expect(formatApiErrorRest({}, 'Some bands were refused.')).toBe('Some bands were refused.')
  })

  it('does not treat a plain message under the key as band errors', () => {
    const { items, rest } = splitIndexedErrors(
      badRequest({ initial_periods: ['Only a static energy tariff takes initial bands.'] }),
      'initial_periods',
    )

    expect(items).toBeNull()
    expect(formatApiErrorRest(rest, 'fallback')).toContain('Only a static energy tariff takes initial bands')
  })

  it('is empty for a failure that is not a response', () => {
    expect(splitIndexedErrors(new Error('offline'), 'initial_periods')).toEqual({ items: null, rest: null })
  })
})

describe('drafted band validation', () => {
  it('needs no tariff, only a price', () => {
    expect(tariffBandDraftSchema.safeParse({ ...defaultTariffPeriodFormValues, price_chf_per_kwh: '0.2' }).success).toBe(true)
    expect(tariffBandDraftSchema.safeParse(defaultTariffPeriodFormValues).success).toBe(false)
  })

  it('takes both times or neither', () => {
    const base = { ...defaultTariffPeriodFormValues, period_type: 'low' as const, price_chf_per_kwh: '0.2' }

    expect(tariffBandDraftSchema.safeParse({ ...base, time_from: '07:00' }).success).toBe(false)
    expect(tariffBandDraftSchema.safeParse({ ...base, time_from: '07:00', time_to: '21:00' }).success).toBe(true)
  })
})
