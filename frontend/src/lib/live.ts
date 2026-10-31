import { useQuery } from '@tanstack/react-query'
import { fetchLiveCurveOrNull, fetchLiveSnapshotOrNull } from './api/live'
import { queryKeys } from './api/queryKeys'
import { BUSINESS_TIME_ZONE, businessDayStartMs, nextIsoDate, todayBusinessIso } from './dates'
import { formatNumber } from './numbers'
import type { LiveCurveBucket, LiveSnapshot, LiveTier } from '../types/api'

export const LIVE_SNAPSHOT_INTERVAL_MS = 15_000
export const LIVE_CURVE_INTERVAL_MS = 60_000

/** Polling cadence of the snapshot: stops for good once the server answered 404 (feature off, no access). */
export function liveSnapshotRefetchInterval(query: { state: { data: unknown } }): number | false {
    return query.state.data === null ? false : LIVE_SNAPSHOT_INTERVAL_MS
}

/**
 * The ZEV's live snapshot, refreshed while the tab is visible. `data` is `null` while the feature is
 * off or the caller may not see the ZEV, and `undefined` until the first answer.
 */
export function useLiveEnergy(zevId: string | undefined) {
    return useQuery({
        queryKey: queryKeys.live.snapshot(zevId ?? ''),
        queryFn: () => fetchLiveSnapshotOrNull(zevId as string),
        enabled: !!zevId,
        refetchInterval: liveSnapshotRefetchInterval,
        refetchIntervalInBackground: false,
        staleTime: 10_000,
        retry: false,
    })
}

/** Today's curve; only requested while the live card is shown. */
export function useLiveCurve(zevId: string | undefined, enabled: boolean) {
    const date = todayBusinessIso()
    return useQuery({
        queryKey: queryKeys.live.curve(zevId ?? '', date),
        queryFn: () => fetchLiveCurveOrNull(zevId as string, date),
        enabled: enabled && !!zevId,
        refetchInterval: LIVE_CURVE_INTERVAL_MS,
        refetchIntervalInBackground: false,
        staleTime: 30_000,
        retry: false,
    })
}

/** A power in W as kW with one decimal, without the unit (for a figure that carries its own). */
export function kwFigure(watts: number): string {
    return formatNumber(watts / 1000, { maxDecimals: 1, minDecimals: 1 })
}

/** A power in W as `1.2 kW` (no-break space). */
export function formatKw(watts: number): string {
    return Number.isFinite(watts) ? `${kwFigure(watts)}\u00a0kW` : '–'
}

const clockFormatter = new Intl.DateTimeFormat('en-GB', {
    timeZone: BUSINESS_TIME_ZONE,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hourCycle: 'h23',
})
const clockMinuteFormatter = new Intl.DateTimeFormat('en-GB', {
    timeZone: BUSINESS_TIME_ZONE,
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
})

/** `hh:mm:ss` of an instant in the business timezone. */
export function formatClock(value: string | number | Date): string {
    return clockFormatter.format(new Date(value))
}

/** `hh:mm` of an instant in the business timezone. */
export function formatClockMinutes(value: string | number | Date): string {
    return clockMinuteFormatter.format(new Date(value))
}

/** The live card is shown only while the server answered and at least one live source exists. */
export function showLiveCard(snapshot: LiveSnapshot | null | undefined): snapshot is LiveSnapshot {
    return !!snapshot && snapshot.coverage.live_sources > 0
}

export interface LiveCardState {
    tier: LiveTier
    /** Managers, viewers and admins get the per-point rows and so the reason a tier is `none`. */
    detailed: boolean
    /** The ZEV's production is a known total (tiers `production` and `exact`). */
    showProduction: boolean
    /** Consumption, spare power and local share are known (tier `exact` only). */
    showExact: boolean
    /** The viewer's own consumption is complete and may be shown. */
    ownConsumption: boolean
    ownProduction: boolean
    /** The viewer's local/grid split: shown at `exact`, or withheld as inconsistent, never below `exact`. */
    ownSplit: 'shown' | 'inconsistent' | 'none'
    ownProductionSplit: boolean
}

/** What the live card may say for a snapshot, or `null` when the card is not shown at all. */
export function liveCardState(snapshot: LiveSnapshot | null | undefined): LiveCardState | null {
    if (!showLiveCard(snapshot)) return null
    const { tier, own } = snapshot
    const exact = tier === 'exact'
    const ownReady = tier !== 'none' && !!own?.complete
    const ownConsumption = ownReady && own.consumption_w !== null
    const ownProduction = ownReady && own.production_w !== null
    let ownSplit: LiveCardState['ownSplit'] = 'none'
    if (exact && ownReady) {
        if (own.split_withheld_reason === 'inconsistent') ownSplit = 'inconsistent'
        else if (ownConsumption && own.local_w !== null && own.grid_w !== null) ownSplit = 'shown'
    }
    return {
        tier,
        detailed: snapshot.points !== undefined,
        showProduction: tier !== 'none' && snapshot.production_w !== null,
        showExact: exact,
        ownConsumption,
        ownProduction,
        ownSplit,
        ownProductionSplit: exact && ownProduction && own.to_zev_w !== null && own.to_grid_w !== null,
    }
}

export interface LiveCurveRow {
    /** Epoch ms of the bucket start. */
    ts: number
    /** kW; `null` is a gap (never interpolated). */
    production: number | null
    consumption: number | null
    own: number | null
}

const toKw = (watts: number | null | undefined): number | null => (watts === null || watts === undefined ? null : watts / 1000)

/**
 * Chart rows from the day's buckets. A `none` bucket is all gaps; consumption exists only in `exact`
 * buckets (the server sends it only there), production from tier `production` up.
 */
export function liveCurveRows(buckets: LiveCurveBucket[]): LiveCurveRow[] {
    return buckets.map((bucket) => {
        const known = bucket.tier !== 'none'
        return {
            ts: Date.parse(bucket.start),
            production: known ? toKw(bucket.production_w) : null,
            consumption: bucket.tier === 'exact' ? toKw(bucket.consumption_w) : null,
            own: known ? toKw(bucket.own_consumption_w) : null,
        }
    })
}

/** The x range of a civil day (`YYYY-MM-DD`) in epoch ms, and a tick every three hours. */
export function liveDayAxis(isoDate: string): { start: number; end: number; ticks: number[] } {
    const start = businessDayStartMs(isoDate)
    const end = businessDayStartMs(nextIsoDate(isoDate))
    const ticks: number[] = []
    for (let tick = start; tick <= end; tick += 3 * 3_600_000) ticks.push(tick)
    return { start, end, ticks }
}
