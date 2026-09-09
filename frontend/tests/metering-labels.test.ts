import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import { formatMeteringBucketLabel } from '../src/lib/meteringLabels'
import type { AppSettings } from '../src/types/api'

const SAVED_TZ = process.env.TZ

const settings: AppSettings = {
  date_format_short: 'dd.MM.yyyy',
  date_format_long: 'd MMMM yyyy',
  date_time_format: 'dd.MM.yyyy HH:mm',
  updated_at: '',
}

beforeAll(() => {
  // The backend buckets metering readings in UTC (TruncDay/TruncHour/TruncMonth
  // with tzinfo=utc). West of UTC is where local-getter drift would show up
  // first: a UTC-midnight bucket rolls back to the previous local day.
  process.env.TZ = 'America/New_York'
})

afterAll(() => {
  if (SAVED_TZ === undefined) {
    delete process.env.TZ
  } else {
    process.env.TZ = SAVED_TZ
  }
})

describe('formatMeteringBucketLabel', () => {
  it('keeps the UTC day for a daily bucket, not the local-getter-shifted day', () => {
    // UTC midnight on Jan 2 is still Jan 1 evening in America/New_York.
    expect(formatMeteringBucketLabel('2026-01-02T00:00:00+00:00', 'day', settings)).toBe('02.01.2026')
  })

  it('keeps the UTC hour for an hourly bucket, not the local-getter-shifted hour', () => {
    expect(formatMeteringBucketLabel('2026-01-02T14:00:00+00:00', 'hour', settings)).toBe('02.01.2026 14:00')
  })

  it('keeps the UTC month for a monthly bucket at a year boundary', () => {
    // UTC midnight on Jan 1 is still December 31 evening in America/New_York.
    expect(formatMeteringBucketLabel('2026-01-01T00:00:00+00:00', 'month', settings)).toBe('Jan 2026')
  })

  it('falls back to the raw bucket string when it cannot be parsed', () => {
    expect(formatMeteringBucketLabel('not-a-date', 'day', settings)).toBe('not-a-date')
  })
})
