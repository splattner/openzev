export type CsvColumnMap = {
    meter_id: string
    timestamp: string
    energy_kwh: string
    direction: string
    energy_start: string
}

export const defaultColumnMap: CsvColumnMap = {
    meter_id: 'meter_id',
    timestamp: 'timestamp',
    energy_kwh: 'energy_kwh',
    direction: 'direction',
    energy_start: '4',
}

export const standardHeaderlessColumnMap: CsvColumnMap = {
    meter_id: '0',
    timestamp: '1',
    energy_kwh: '2',
    direction: '',
    energy_start: '',
}

export const dailyHeadedColumnMap: CsvColumnMap = {
    meter_id: 'meter_id',
    timestamp: 'date',
    energy_kwh: '',
    direction: '',
    energy_start: '00:00',
}

export const dailyHeaderlessColumnMap: CsvColumnMap = {
    meter_id: '0',
    timestamp: '1',
    energy_kwh: '',
    direction: '',
    energy_start: '2',
}

export type CsvFormatProfile = 'standard' | 'daily_15min'

export function csvConfigFor(
    hasHeader: boolean,
    profile: CsvFormatProfile = 'standard',
): { delimiter: string; columnMap: CsvColumnMap } {
    if (profile === 'daily_15min') {
        return hasHeader
            ? { delimiter: ',', columnMap: { ...dailyHeadedColumnMap } }
            : { delimiter: ';', columnMap: { ...dailyHeaderlessColumnMap } }
    }
    return hasHeader
        ? { delimiter: ',', columnMap: { ...defaultColumnMap } }
        : { delimiter: ';', columnMap: { ...standardHeaderlessColumnMap } }
}

export type PreviewStamp = {
    fileName: string
    fileSize: number
    lastModified: number
    source: string
    zevId: string
    hasHeader: boolean
    delimiter: string
    formatProfile: string
    timestampFormat: string
    intervalMinutes: string
    valuesCount: string
    overwriteExisting: boolean
    columnMap: CsvColumnMap
}

export function previewStampsEqual(a: PreviewStamp | null, b: PreviewStamp | null): boolean {
    if (a === null || b === null) return false
    const normalize = (stamp: PreviewStamp) => ({
        ...stamp,
        // Numeric config is kept as strings in state: "096" and "96" are the
        // same configuration and must not invalidate a valid preview.
        // Strict parsing (not parseInt): "96foo" is invalid input and must
        // invalidate the stamp just like the config validators reject it.
        intervalMinutes: normalizePositiveInt(stamp.intervalMinutes),
        valuesCount: normalizePositiveInt(stamp.valuesCount),
        // "\t" (escape) and a literal tab are the same delimiter backend-side.
        delimiter: normalizeDelimiter(stamp.delimiter),
    })
    return JSON.stringify(normalize(a)) === JSON.stringify(normalize(b))
}

function normalizePositiveInt(raw: string): string {
    const parsed = parsePositiveInt(raw)
    return parsed === null ? `invalid:${raw}` : String(parsed)
}

/**
 * Client-side preflight for the backend `_check_timestamp_format` full-date rule:
 * an explicit format must capture year, month, and day, otherwise the server
 * rejects it (e.g. year-less `%d.%m` would silently land data in 1900).
 * Empty means auto-detect and is always valid.
 *
 * `%j` (day of year) implies month+day when combined with a year, so
 * `%Y-%j` — accepted by the backend probe — is valid here too. Week-based
 * Week formats require a matching year and weekday. The server probe remains
 * authoritative for directive support and locale-specific parsing.
 */
export function isValidTimestampFormat(format: string): boolean {
    if (format === '') return true
    if (!format.includes('%')) return false
    // Escaped percent signs are literals, not date directives.
    const directives = format.replace(/%%/g, '')
    const hasCalendarYear = /%[Yy]/.test(directives)
    const hasMonthAndDay = /%[mBb]/.test(directives) && /%d/.test(directives)
    const hasDayOfYear = /%j/.test(directives)
    const hasWeekday = /%[auwA]/.test(directives)
    const hasCalendarWeek = /%[UW]/.test(directives) && hasWeekday
    const hasIsoWeek = /%G/.test(directives) && /%V/.test(directives) && hasWeekday
    return (hasCalendarYear && (hasMonthAndDay || hasDayOfYear || hasCalendarWeek)) || hasIsoWeek
}

/**
 * Mirrors backend `_normalise_delimiter`: the UI delimiter field cannot type
 * a literal tab, so `\t` (backslash-t) means tab. Both the escape and a real
 * tab character are valid; anything else must be exactly one character.
 */
export function isValidDelimiter(delimiter: string): boolean {
    if (delimiter === '\\t' || delimiter === '\t') return true
    return delimiter.length === 1
}

export function normalizeDelimiter(delimiter: string): string {
    if (delimiter === '\\t') return '\t'
    return delimiter
}

// Mirrors backend/metering/importers/limits.py:MAX_UPLOAD_BYTES.
// Cross-layer parity is asserted by frontend/tests/imports-samples.test.ts;
// the backend value itself is pinned in backend/metering/test_import_limits.py.
export const MAX_UPLOAD_BYTES = 50 * 1024 * 1024

export function isLegacyExcel(name: string): boolean {
    return /\.xls$/i.test(name) && !/\.xlsx$/i.test(name)
}

export function parsePositiveInt(raw: string): number | null {
    if (!/^\d+$/.test(raw.trim())) return null
    const value = parseInt(raw.trim(), 10)
    return Number.isSafeInteger(value) ? value : null
}
