import type { AppSettings, MeteringPoint } from '../types/api'
import { BUSINESS_TIME_ZONE, zonedParts } from './dates'

/**
 * The backend truncates day and month buckets at Swiss midnight and hour
 * buckets at UTC hours, and serializes each with its offset (ADR 0026). A
 * bucket is an instant, so its label is read in the business timezone —
 * never from the string's date part and never in the viewer's own zone,
 * which would put someone abroad on a different day than the invoice.
 */

function pad(value: number): string {
    return String(value).padStart(2, '0')
}

function bucketParts(date: Date) {
    const p = zonedParts(date)
    return {
        dayPadded: pad(p.day),
        monthPadded: pad(p.month),
        monthShort: new Intl.DateTimeFormat(undefined, { month: 'short', timeZone: BUSINESS_TIME_ZONE }).format(date),
        year: p.year,
        hoursPadded: pad(p.hours),
        minutesPadded: pad(p.minutes),
    }
}

function formatBucketShortDate(bucket: string, settings: AppSettings): string {
    const date = new Date(bucket)
    if (isNaN(date.getTime())) return bucket
    const p = bucketParts(date)
    switch (settings.date_format_short) {
        case 'dd.MM.yyyy':
            return `${p.dayPadded}.${p.monthPadded}.${p.year}`
        case 'dd/MM/yyyy':
            return `${p.dayPadded}/${p.monthPadded}/${p.year}`
        case 'MM/dd/yyyy':
            return `${p.monthPadded}/${p.dayPadded}/${p.year}`
        case 'yyyy-MM-dd':
            return `${p.year}-${p.monthPadded}-${p.dayPadded}`
        default:
            return bucket
    }
}

function formatBucketDateTime(bucket: string, settings: AppSettings): string {
    const date = new Date(bucket)
    if (isNaN(date.getTime())) return bucket
    const p = bucketParts(date)
    switch (settings.date_time_format) {
        case 'dd.MM.yyyy HH:mm':
            return `${p.dayPadded}.${p.monthPadded}.${p.year} ${p.hoursPadded}:${p.minutesPadded}`
        case 'dd/MM/yyyy HH:mm':
            return `${p.dayPadded}/${p.monthPadded}/${p.year} ${p.hoursPadded}:${p.minutesPadded}`
        case 'MM/dd/yyyy HH:mm':
            return `${p.monthPadded}/${p.dayPadded}/${p.year} ${p.hoursPadded}:${p.minutesPadded}`
        case 'yyyy-MM-dd HH:mm':
            return `${p.year}-${p.monthPadded}-${p.dayPadded} ${p.hoursPadded}:${p.minutesPadded}`
        default:
            return bucket
    }
}

function formatBucketMonthYear(bucket: string): string {
    const date = new Date(bucket)
    if (isNaN(date.getTime())) return bucket
    const p = bucketParts(date)
    return `${p.monthShort} ${p.year}`
}

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
            return formatBucketDateTime(bucket, settings)
        }
        if (resolution === 'month') {
            return formatBucketMonthYear(bucket)
        }
        return formatBucketShortDate(bucket, settings)
    } catch {
        return bucket
    }
}

/**
 * Pick the i18n key for a meter's OUT-direction readings.
 *
 * `OUT` means different things depending on the meter (`allocation/read_model.py`):
 * on a `production` meter it *is* the production, not an export to the grid;
 * "feed-in" only describes `OUT` on a `bidirectional` meter, where it's
 * production exceeding local consumption. Labeling a pure-production meter's
 * output as "feed-in" misdescribes what the number means.
 */
export function outReadingLabelKey(
    meterType: MeteringPoint['meter_type'] | undefined,
    whenProduction: string,
    otherwise: string,
): string {
    return meterType === 'production' ? whenProduction : otherwise
}

/**
 * Label for a metering-point `<option>` — meter ID plus enough to tell two
 * similarly-named meters apart at a glance (type, active/inactive, ZEV)
 * without opening each one (#643). Reuses the same meter-type and
 * active-state strings already shown on the Metering Points page, so the
 * two lists describe a meter the same way.
 */
export function meteringPointOptionLabel(
    mp: Pick<MeteringPoint, 'meter_id' | 'meter_type' | 'is_active'>,
    zevName: string | undefined,
    translate: (key: string) => string,
): string {
    const parts = [mp.meter_id, translate(`pages.meteringPoints.meterTypes.${mp.meter_type}`)]
    if (!mp.is_active) {
        parts.push(translate('pages.meteringPoints.inactive'))
    }
    if (zevName) {
        parts.push(zevName)
    }
    return parts.join(' · ')
}
