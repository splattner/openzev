import { useQuery } from '@tanstack/react-query'
import { fetchProductionForecastOrNull } from './api/live'
import { queryKeys } from './api/queryKeys'
import { formatBusinessIsoDate } from './dates'
import { formatClockMinutes } from './live'
import type { ForecastHour, ForecastPeakWindow, ProductionForecast } from '../types/api'

export const FORECAST_INTERVAL_MS = 15 * 60_000

/**
 * The ZEV's expected production, refreshed every 15 minutes. `data` is `null` while the feature is off
 * or the caller may not see the ZEV, and `undefined` until the first answer. The forecast changes
 * slowly, so there is no focus refetch.
 */
export function useProductionForecast(zevId: string | undefined, enabled = true) {
    return useQuery({
        queryKey: queryKeys.live.forecast(zevId ?? ''),
        queryFn: () => fetchProductionForecastOrNull(zevId as string),
        enabled: enabled && !!zevId,
        refetchInterval: (query) => (query.state.data === null ? false : FORECAST_INTERVAL_MS),
        refetchIntervalInBackground: false,
        refetchOnWindowFocus: false,
        staleTime: 5 * 60_000,
        retry: false,
    })
}

export interface ForecastRow {
    /** Epoch ms of the hour's start. */
    ts: number
    /** kW. */
    power: number
    /** kW, `[min, max]`; `null` when the forecast gives no band. */
    band: [number, number] | null
}

/** Chart rows from the hours; watts become kW. */
export function forecastRows(hours: ForecastHour[]): ForecastRow[] {
    return hours.map((hour) => ({
        ts: Date.parse(hour.start),
        power: hour.power_w / 1000,
        band: hour.min_w !== null && hour.max_w !== null ? [hour.min_w / 1000, hour.max_w / 1000] : null,
    }))
}

/** Whether the forecast has anything to show: at least one plant with hours. */
export function hasForecast(forecast: ProductionForecast | null | undefined): forecast is ProductionForecast {
    return !!forecast && forecast.plants_with_forecast > 0 && forecast.hours.length > 0
}

/** The peak window that is running or next: the first that has not ended yet. */
export function nextPeakWindow(windows: ForecastPeakWindow[], now: Date = new Date()): ForecastPeakWindow | undefined {
    return windows.find((window) => Date.parse(window.to) > now.getTime())
}

/** `today`, `tomorrow` or an ISO civil day: the caller turns the first two into words. */
export function peakDayKind(window: ForecastPeakWindow, now: Date = new Date()): 'today' | 'tomorrow' | 'date' {
    const today = formatBusinessIsoDate(now)
    if (window.date === today) return 'today'
    const tomorrow = formatBusinessIsoDate(new Date(now.getTime() + 24 * 3_600_000))
    return window.date === tomorrow ? 'tomorrow' : 'date'
}

/** `10:00–14:00` of a window in the business timezone. */
export function peakRange(window: ForecastPeakWindow): string {
    return `${formatClockMinutes(window.from)}–${formatClockMinutes(window.to)}`
}
