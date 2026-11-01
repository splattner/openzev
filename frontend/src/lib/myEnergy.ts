import { useQuery } from '@tanstack/react-query'
import { fetchOwnSeries } from './api/live'
import { queryKeys } from './api/queryKeys'
import { businessDayStartMs, nextIsoDate } from './dates'
import { liveCurveRows } from './live'
import type { ForecastHour, LiveCurve, OwnHistoryRow, OwnSeries } from '../types/api'

/** The views of the "My energy system" page; the URL carries the choice as `?range=`. `tomorrow` only exists while there is a forecast for it. */
export type MyEnergyRange = 'today' | 'tomorrow' | 'week' | 'period'
export const MY_ENERGY_RANGES: MyEnergyRange[] = ['today', 'tomorrow', 'week', 'period']
export const MY_ENERGY_DEFAULT_RANGE: MyEnergyRange = 'today'

export function parseMyEnergyRange(value: string | null | undefined): MyEnergyRange {
    return MY_ENERGY_RANGES.includes(value as MyEnergyRange) ? (value as MyEnergyRange) : MY_ENERGY_DEFAULT_RANGE
}

/** `YYYY-MM-DD` moved by whole days; calendar arithmetic in UTC, so no DST shifts it. */
export function shiftIsoDate(isoDate: string, days: number): string {
    return new Date(Date.parse(`${isoDate}T00:00:00Z`) + days * 86_400_000).toISOString().slice(0, 10)
}

/** The last `days` civil days up to and including `todayIso`. */
export function lastDaysRange(todayIso: string, days: number): { from: string; to: string } {
    return { from: shiftIsoDate(todayIso, -(days - 1)), to: todayIso }
}

/**
 * Whether the sidebar offers "My energy system". The live flag alone is enough (it implies the
 * energy data feature). Without it the page still has history to show: to anybody with community-wide
 * access (they pick a participant), and to a participant who holds a meter an own system can be
 * connected to.
 */
export function showMyEnergyEntry(input: {
    liveEnabled: boolean
    energyDataOn: boolean
    isZevScope: boolean
    holdsHistoryMeter: boolean
}): boolean {
    return input.liveEnabled || (input.energyDataOn && (input.isZevScope || input.holdsHistoryMeter))
}

/** Own-system series of a civil range; off while `enabled` is false (feature off, nobody selected). */
export function useOwnSeries(
    params: { zevId: string | undefined; dateFrom: string; dateTo: string; bucket: OwnSeries['bucket']; participantId?: string },
    enabled: boolean,
) {
    const { zevId, dateFrom, dateTo, bucket, participantId } = params
    return useQuery({
        queryKey: queryKeys.live.ownSeries(zevId ?? '', participantId ?? '', dateFrom, dateTo, bucket),
        queryFn: () => fetchOwnSeries({ zevId: zevId as string, dateFrom, dateTo, bucket, participantId }),
        enabled: enabled && !!zevId && !!dateFrom && !!dateTo,
        staleTime: 60_000,
        retry: false,
    })
}

/** A quarter-hour series as the curve's own history: kWh per quarter hour is a mean power of kWh x 4000 W. */
export function ownHistoryFromSeries(series: OwnSeries | null | undefined): { rows: OwnHistoryRow[]; through: string | null } {
    const timeline = series?.gross?.timeline ?? []
    return {
        rows: timeline.map((item) => ({
            start: item.bucket,
            consumption_w: item.consumption_kwh * 4000,
            production_w: item.production_kwh * 4000,
        })),
        through: series?.history_through ?? null,
    }
}

export interface TodayRow {
    /** Epoch ms. */
    ts: number
    /** The ZEV's live totals, kW; live only, `null` is a gap. */
    production: number | null
    consumption: number | null
    /** The viewer's own consumption and production from stored history, before the hand-over. */
    ownHistory: number | null
    ownHistoryProduction: number | null
    /** The same from live buckets, from the hand-over on. */
    ownLive: number | null
    ownLiveProduction: number | null
    /** The expected production of the ZEV's plants, kW, flat across its hour; `null` where there is no forecast. */
    forecast: number | null
    /** `[min, max]` of the expected production, kW, where the forecast gives a band. */
    forecastBand: [number, number] | null
}

const HISTORY_INTERVAL_MS = 900_000
const LIVE_STEP_MS = 300_000

const blankRow = (ts: number): TodayRow => ({
    ts, production: null, consumption: null, ownHistory: null, ownHistoryProduction: null, ownLive: null, ownLiveProduction: null,
    forecast: null, forecastBand: null,
})

/**
 * The Today chart's rows: one merged "own" line. Where the two sources overlap, history wins: a history
 * interval is used before `through` (the end of the last interval the own source synced), a live bucket
 * from `through` on, and where neither has a value there is a gap, never an interpolation. The
 * ZEV totals are live only. The history line is carried to `through`, so it ends where live begins.
 * The forecast of the civil day `forecast.date` is drawn flat across each of its hours, past hours included
 * (they show what was expected next to what happened).
 */
export function todayRows(
    curve: LiveCurve | null | undefined,
    history: OwnHistoryRow[],
    through: string | null,
    forecast?: { date: string; hours: ForecastHour[] },
): TodayRow[] {
    const throughMs = through ? Date.parse(through) : null
    const byTs = new Map<number, TodayRow>()
    const row = (ts: number) => {
        let found = byTs.get(ts)
        if (!found) byTs.set(ts, (found = blankRow(ts)))
        return found
    }

    for (const live of liveCurveRows(curve?.buckets ?? [])) {
        const target = row(live.ts)
        target.production = live.production
        target.consumption = live.consumption
        if (throughMs === null || live.ts >= throughMs) {
            target.ownLive = live.own
            target.ownLiveProduction = live.ownProduction
        }
    }

    // A history interval is a mean over 15 minutes, so it is drawn flat across its length, one value per
    // 5-minute step. That keeps the line connected next to the live rows and leaves a missing interval a gap.
    let last: OwnHistoryRow | null = null
    for (const item of history) {
        const start = Date.parse(item.start)
        if (throughMs !== null && start >= throughMs) continue
        for (let ts = start; ts < start + HISTORY_INTERVAL_MS && (throughMs === null || ts < throughMs); ts += LIVE_STEP_MS) {
            const target = row(ts)
            target.ownHistory = item.consumption_w / 1000
            target.ownHistoryProduction = item.production_w / 1000
        }
        if (!last || start > Date.parse(last.start)) last = item
    }
    if (forecast) {
        const dayStart = businessDayStartMs(forecast.date)
        const dayEnd = businessDayStartMs(nextIsoDate(forecast.date))
        for (const hour of forecast.hours) {
            const start = Date.parse(hour.start)
            for (let ts = start; ts < start + 3_600_000; ts += LIVE_STEP_MS) {
                if (ts < dayStart || ts >= dayEnd) continue
                const target = row(ts)
                target.forecast = hour.power_w / 1000
                target.forecastBand = hour.min_w !== null && hour.max_w !== null ? [hour.min_w / 1000, hour.max_w / 1000] : null
            }
        }
    }
    if (throughMs !== null && last) {
        const edge = row(throughMs)
        edge.ownHistory = last.consumption_w / 1000
        edge.ownHistoryProduction = last.production_w / 1000
    }
    return [...byTs.values()].sort((a, b) => a.ts - b.ts)
}
