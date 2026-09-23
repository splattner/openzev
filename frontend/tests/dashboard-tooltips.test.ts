import { describe, expect, it } from 'vitest'
import { formatConsumptionMixTooltip, formatProductionMixTooltip } from '../src/lib/dashboardTooltips'
describe('formatProductionMixTooltip', () => {
  it('formats the rate as percent when dataKey matches, even with a translated series name', () => {
    expect(
      formatProductionMixTooltip(45.25, 'Eigenverbrauch %', 'self_consumption_rate', 'Eigenverbrauch %'),
    ).toEqual(['45.3\u00a0%', 'Eigenverbrauch %'])
  })

  it('formats kWh series and keeps the passed series name', () => {
    expect(
      formatProductionMixTooltip(1234.56, 'Exportiert', 'exported_kwh', 'Eigenverbrauch %'),
    ).toEqual(['1234.56 kWh', 'Exportiert'])
  })

  it('formats small kWh buckets with two decimals', () => {
    expect(
      formatProductionMixTooltip(0.25, 'From grid', 'imported_kwh', 'Self-consumed %'),
    ).toEqual(['0.25 kWh', 'From grid'])
  })
})

describe('formatConsumptionMixTooltip', () => {
  it('formats the from-ZEV rate as percent by dataKey, with the translated label', () => {
    expect(formatConsumptionMixTooltip(62.5, 'Aus ZEV %', 'from_zev_rate', 'Aus ZEV %')).toEqual([
      '62.5\u00a0%',
      'Aus ZEV %',
    ])
  })

  it('formats kWh series and keeps the passed series name', () => {
    expect(formatConsumptionMixTooltip(12.345, 'Aus Netz', 'imported_kwh', 'Aus ZEV %')).toEqual([
      '12.35 kWh',
      'Aus Netz',
    ])
  })
})
