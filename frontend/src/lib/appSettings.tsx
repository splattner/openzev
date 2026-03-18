import { createContext, useContext, useMemo, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchAppSettings } from './api'
import { useAuth } from './auth'
import type { AppSettings, DateTimeFormat, LongDateFormat, ShortDateFormat } from '../types/api'

export const DEFAULT_APP_SETTINGS: AppSettings = {
    date_format_short: 'dd.MM.yyyy',
    date_format_long: 'd MMMM yyyy',
    date_time_format: 'dd.MM.yyyy HH:mm',
    updated_at: '',
}

export const SHORT_DATE_FORMAT_OPTIONS: Array<{ value: ShortDateFormat; label: string }> = [
    { value: 'dd.MM.yyyy', label: 'DD.MM.YYYY' },
    { value: 'dd/MM/yyyy', label: 'DD/MM/YYYY' },
    { value: 'MM/dd/yyyy', label: 'MM/DD/YYYY' },
    { value: 'yyyy-MM-dd', label: 'YYYY-MM-DD' },
]

export const LONG_DATE_FORMAT_OPTIONS: Array<{ value: LongDateFormat; label: string }> = [
    { value: 'd MMMM yyyy', label: 'D MMMM YYYY' },
    { value: 'd. MMMM yyyy', label: 'D. MMMM YYYY' },
    { value: 'MMMM d, yyyy', label: 'MMMM D, YYYY' },
    { value: 'yyyy-MM-dd', label: 'YYYY-MM-DD' },
]

export const DATE_TIME_FORMAT_OPTIONS: Array<{ value: DateTimeFormat; label: string }> = [
    { value: 'dd.MM.yyyy HH:mm', label: 'DD.MM.YYYY HH:mm' },
    { value: 'dd/MM/yyyy HH:mm', label: 'DD/MM/YYYY HH:mm' },
    { value: 'MM/dd/yyyy HH:mm', label: 'MM/DD/YYYY HH:mm' },
    { value: 'yyyy-MM-dd HH:mm', label: 'YYYY-MM-DD HH:mm' },
]

interface AppSettingsContextValue {
    settings: AppSettings
    isLoading: boolean
}

const AppSettingsContext = createContext<AppSettingsContextValue | undefined>(undefined)

function pad(value: number) {
    return String(value).padStart(2, '0')
}

function parseDateValue(value: string): Date | null {
    if (!value) return null

    const isoDateMatch = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
    if (isoDateMatch) {
        const [, year, month, day] = isoDateMatch
        return new Date(Number(year), Number(month) - 1, Number(day))
    }

    const parsed = new Date(value)
    return Number.isNaN(parsed.getTime()) ? null : parsed
}

function formatDateParts(date: Date) {
    return {
        day: date.getDate(),
        dayPadded: pad(date.getDate()),
        hoursPadded: pad(date.getHours()),
        minutesPadded: pad(date.getMinutes()),
        month: date.getMonth() + 1,
        monthPadded: pad(date.getMonth() + 1),
        monthLong: new Intl.DateTimeFormat(undefined, { month: 'long' }).format(date),
        monthShort: new Intl.DateTimeFormat(undefined, { month: 'short' }).format(date),
        year: date.getFullYear(),
    }
}

export function formatDateByPattern(value: string | null | undefined, pattern: ShortDateFormat | LongDateFormat): string {
    if (!value) return '—'

    const date = parseDateValue(value)
    if (!date) return value

    const parts = formatDateParts(date)

    switch (pattern) {
        case 'dd.MM.yyyy':
            return `${parts.dayPadded}.${parts.monthPadded}.${parts.year}`
        case 'dd/MM/yyyy':
            return `${parts.dayPadded}/${parts.monthPadded}/${parts.year}`
        case 'MM/dd/yyyy':
            return `${parts.monthPadded}/${parts.dayPadded}/${parts.year}`
        case 'yyyy-MM-dd':
            return `${parts.year}-${parts.monthPadded}-${parts.dayPadded}`
        case 'd MMMM yyyy':
            return `${parts.day} ${parts.monthLong} ${parts.year}`
        case 'd. MMMM yyyy':
            return `${parts.day}. ${parts.monthLong} ${parts.year}`
        case 'MMMM d, yyyy':
            return `${parts.monthLong} ${parts.day}, ${parts.year}`
        default:
            return value
    }
}

export function formatShortDate(value: string | null | undefined, settings: AppSettings = DEFAULT_APP_SETTINGS): string {
    return formatDateByPattern(value, settings.date_format_short)
}

export function formatLongDate(value: string | null | undefined, settings: AppSettings = DEFAULT_APP_SETTINGS): string {
    return formatDateByPattern(value, settings.date_format_long)
}

export function formatDateTime(value: string | null | undefined, settings: AppSettings = DEFAULT_APP_SETTINGS): string {
    if (!value) return '—'

    const date = parseDateValue(value)
    if (!date) return value

    const parts = formatDateParts(date)
    if (!value.includes('T') && !value.includes(' ')) {
        return formatDateByPattern(value, settings.date_time_format.split(' ')[0] as ShortDateFormat)
    }

    switch (settings.date_time_format) {
        case 'dd.MM.yyyy HH:mm':
            return `${parts.dayPadded}.${parts.monthPadded}.${parts.year} ${parts.hoursPadded}:${parts.minutesPadded}`
        case 'dd/MM/yyyy HH:mm':
            return `${parts.dayPadded}/${parts.monthPadded}/${parts.year} ${parts.hoursPadded}:${parts.minutesPadded}`
        case 'MM/dd/yyyy HH:mm':
            return `${parts.monthPadded}/${parts.dayPadded}/${parts.year} ${parts.hoursPadded}:${parts.minutesPadded}`
        case 'yyyy-MM-dd HH:mm':
            return `${parts.year}-${parts.monthPadded}-${parts.dayPadded} ${parts.hoursPadded}:${parts.minutesPadded}`
        default:
            return value
    }
}

export function formatMonthYear(value: string | null | undefined): string {
    if (!value) return '—'

    const date = parseDateValue(value)
    if (!date) return value

    const parts = formatDateParts(date)
    return `${parts.monthShort} ${parts.year}`
}

export function toDayJsDateFormat(pattern: ShortDateFormat): string {
    switch (pattern) {
        case 'dd.MM.yyyy':
            return 'DD.MM.YYYY'
        case 'dd/MM/yyyy':
            return 'DD/MM/YYYY'
        case 'MM/dd/yyyy':
            return 'MM/DD/YYYY'
        case 'yyyy-MM-dd':
            return 'YYYY-MM-DD'
        default:
            return 'DD.MM.YYYY'
    }
}

export function AppSettingsProvider({ children }: { children: ReactNode }) {
    const { isAuthenticated } = useAuth()
    const settingsQuery = useQuery({
        queryKey: ['app-settings'],
        queryFn: fetchAppSettings,
        enabled: isAuthenticated,
    })

    const value = useMemo<AppSettingsContextValue>(
        () => ({
            settings: settingsQuery.data ?? DEFAULT_APP_SETTINGS,
            isLoading: isAuthenticated ? settingsQuery.isLoading : false,
        }),
        [isAuthenticated, settingsQuery.data, settingsQuery.isLoading],
    )

    return <AppSettingsContext.Provider value={value}>{children}</AppSettingsContext.Provider>
}

export function useAppSettings() {
    const context = useContext(AppSettingsContext)
    if (!context) {
        throw new Error('useAppSettings must be used within AppSettingsProvider')
    }
    return context
}