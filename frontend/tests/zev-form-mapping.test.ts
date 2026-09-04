import { describe, expect, it } from 'vitest'
import { getDefaultZevForm, mapZevToForm } from '../src/lib/zevForm'
import type { Zev } from '../src/types/api'

function zev(overrides: Partial<Zev> = {}): Zev {
  return {
    id: 'z-1',
    name: 'Demo',
    start_date: '2026-01-01',
    owner: 2,
    zev_type: 'vzev',
    billing_interval: 'monthly',
    invoice_prefix: 'INV',
    invoice_language: 'de',
    payment_term_days: 30,
    ...overrides,
  } as Zev
}

describe('zev form mapping', () => {
  // The settings page rebuilds its form from whatever the list endpoint
  // returns. A field the mapper forgets is not a visibly missing input — it
  // silently falls back to its default, so a saved value looks like it
  // reverted. Keeping the two shapes in step is what stops that.
  it('produces every field the default form declares', () => {
    expect(Object.keys(mapZevToForm(zev())).sort()).toEqual(
      expect.arrayContaining(Object.keys(getDefaultZevForm()).sort()),
    )
  })

  it('carries the band-itemisation setting through', () => {
    expect(mapZevToForm(zev({ itemize_tariff_bands: true })).itemize_tariff_bands).toBe(true)
    expect(mapZevToForm(zev({ itemize_tariff_bands: false })).itemize_tariff_bands).toBe(false)
  })

  it('defaults band itemisation to off when the api omits it', () => {
    expect(mapZevToForm(zev()).itemize_tariff_bands).toBe(false)
    expect(getDefaultZevForm().itemize_tariff_bands).toBe(false)
  })
})
