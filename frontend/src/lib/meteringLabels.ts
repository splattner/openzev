import { formatDateTime, formatMonthYear, formatShortDate } from './appSettings'
import type { AppSettings } from '../types/api'

/**
 * Format a metering bucket value (day / hour / month) for chart axes and
 * tooltips. Falls back to the raw bucket string if the value cannot be parsed.
 */
export function formatMeteringBucketLabel(
    bucket: string,
    resolution: 'day' | 'hour' | 'month',
    settings: AppSettings,
): string {
    try {
        if (resolution === 'hour') {
            return formatDateTime(bucket, settings)
        }
        if (resolution === 'month') {
            return formatMonthYear(bucket)
        }
        return formatShortDate(bucket, settings)
    } catch {
        return bucket
    }
}
