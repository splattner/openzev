import { describe, expect, it } from 'vitest'
import {
  dashboardKwhStat,
  fromZevRate,
  hourlyKwhTick,
  hourlyKwhTooltipValue,
  kwhTick,
  kwhTooltipValue,
} from '../src/lib/dashboardFormatting'

describe('dashboard chart formatting', () => {
  it('caps dashboard KPI and table values at up to two decimals', () => {
    expect(dashboardKwhStat(1234.567)).toBe('1234.57 kWh')
  })

  it('uses up to two decimals for period-bucket axis ticks', () => {
    expect(kwhTick(1234.567)).toBe('1234.57')
  })

  it('uses up to four decimals for hourly-profile axis ticks', () => {
    expect(hourlyKwhTick(0.005)).toBe('0.005')
  })

  it('keeps period tooltip values at up to two decimals', () => {
    expect(kwhTooltipValue(0.005)).toBe('0.01 kWh')
  })

  it('keeps hourly tooltip values at up to four decimals', () => {
    expect(hourlyKwhTooltipValue(0.005)).toBe('0.005 kWh')
  })

  it('computes the from-ZEV share to one decimal and skips buckets without consumption', () => {
    expect(fromZevRate(1, 3)).toBe(33.3)
    expect(fromZevRate(5, 5)).toBe(100)
    expect(fromZevRate(0, 0)).toBeNull()
  })
})
