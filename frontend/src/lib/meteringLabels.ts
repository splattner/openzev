import type { AppSettings, MeteringPoint } from '../types/api'

/**
 * The backend buckets metering readings in UTC (``TruncDay``/``TruncHour``/
 * ``TruncMonth`` with ``tzinfo=utc`` in ``metering/views.py``) to match how
 * the importer stamps naive CSV timestamps. Formatting a bucket via the
 * shared ``formatDateTime``/``formatShortDate``/``formatMonthYear`` helpers
 * (which read local-time components) would disagree with that UTC bucketing
 * — off by the viewer's UTC offset, and by a whole day for daily/monthly
 * buckets in negative-offset timezones — and with ``RawMeteringTable``,
 * which deliberately reads UTC components for the same reason. So bucket
 * labels get their own UTC-aware formatting here instead of reusing the
 * local-time helpers.
 */

function pad(value: number): string {
    return String(value).padStart(2, '0')
}

function utcParts(date: Date) {
    return {
        day: date.getUTCDate(),
        dayPadded: pad(date.getUTCDate()),
        monthPadded: pad(date.getUTCMonth() + 1),
        monthShort: new Intl.DateTimeFormat(undefined, { month: 'short', timeZone: 'UTC' }).format(date),
        year: date.getUTCFullYear(),
        hoursPadded: pad(date.getUTCHours()),
        minutesPadded: pad(date.getUTCMinutes()),
    }
}

function formatUtcShortDate(bucket: string, settings: AppSettings): string {
    const date = new Date(bucket)
    if (isNaN(date.getTime())) return bucket
    const p = utcParts(date)
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

function formatUtcDateTime(bucket: string, settings: AppSettings): string {
    const date = new Date(bucket)
    if (isNaN(date.getTime())) return bucket
    const p = utcParts(date)
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

function formatUtcMonthYear(bucket: string): string {
    const date = new Date(bucket)
    if (isNaN(date.getTime())) return bucket
    const p = utcParts(date)
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
            return formatUtcDateTime(bucket, settings)
        }
        if (resolution === 'month') {
            return formatUtcMonthYear(bucket)
        }
        return formatUtcShortDate(bucket, settings)
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
