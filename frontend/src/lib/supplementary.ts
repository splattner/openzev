import { useQuery, type QueryClient } from '@tanstack/react-query'
import { API_BASE_URL } from './api/client'
import { queryKeys } from './api/queryKeys'
import { fetchEligibleOrNull } from './api/supplementary'
import type {
    EligibleMeteringPoint,
    GrossEnergy,
    LiveState,
    SourceCapability,
    SupplementarySource,
    SupplementaryStatus,
} from '../types/api'

/** i18n key explaining why a rate is shown as a dash, or `null` when there is a rate to show. */
export function withheldReasonKey(gross: Pick<GrossEnergy, 'rates_withheld_reason'> | null | undefined): string | null {
    switch (gross?.rates_withheld_reason) {
        case 'low_coverage':
            return 'supplementary.withheld.lowCoverage'
        case 'no_data':
            return 'supplementary.withheld.noData'
        default:
            return null
    }
}

/** Whether the participant's own system reported enough for this period to be shown next to the meter. */
export function hasOwnSystemData(gross: Pick<GrossEnergy, 'rates_withheld_reason'> | null | undefined): boolean {
    return !!gross && !gross.rates_withheld_reason
}

/** Hint for the surplus-meter badge and notes: says where the figures come from once the own system is connected. */
export function behindMeterHintKey(
    whose: 'participant' | 'own',
    gross: Pick<GrossEnergy, 'rates_withheld_reason'> | null | undefined,
): 'behindMeter.participantHint' | 'behindMeter.participantHintConnected' | 'behindMeter.ownHint' | 'behindMeter.ownHintConnected' {
    if (whose === 'participant') return hasOwnSystemData(gross) ? 'behindMeter.participantHintConnected' : 'behindMeter.participantHint'
    return hasOwnSystemData(gross) ? 'behindMeter.ownHintConnected' : 'behindMeter.ownHint'
}

export type GrossRateKind = 'self_sufficiency' | 'self_consumption'

/**
 * The rate to show for a participant's own-system figures, or `null` for a dash.
 * Never invents a number: a withheld rate (too little data) stays a dash.
 */
export function grossRate(gross: GrossEnergy | null | undefined, kind: GrossRateKind = 'self_sufficiency'): number | null {
    if (!gross || gross.rates_withheld_reason) return null
    return kind === 'self_sufficiency' ? gross.self_sufficiency_rate : gross.self_consumption_rate
}

export type StatusTone = 'success' | 'warning' | 'danger' | 'neutral'

export function statusTone(status: SupplementaryStatus | null | undefined): StatusTone {
    switch (status) {
        case 'ok':
            return 'success'
        case 'pending':
            return 'neutral'
        case 'error':
            return 'warning'
        case 'reconnect_required':
            return 'danger'
        default:
            return 'neutral'
    }
}

export const STATUS_BADGE_CLASS: Record<StatusTone, string> = {
    success: 'badge badge-success',
    warning: 'badge badge-warning',
    danger: 'badge badge-danger',
    neutral: 'badge badge-neutral',
}

/** The URL a push client posts to, absolute so it can be pasted into Home Assistant or n8n. */
export function ingestUrl(origin: string = typeof window === 'undefined' ? '' : window.location.origin): string {
    const base = /^https?:\/\//.test(API_BASE_URL) ? API_BASE_URL.replace(/\/+$/, '') : `${origin}${API_BASE_URL}`.replace(/\/+$/, '')
    return `${base}/metering/supplementary/ingest/`
}

/** The URL a live push client posts to (`Authorization: Bearer <push token>`). */
export function liveIngestUrl(origin: string = typeof window === 'undefined' ? '' : window.location.origin): string {
    return ingestUrl(origin).replace(/\/supplementary\/ingest\/$/, '/live/ingest/')
}

/** The sample a live push client posts: power at the meter, >0 drawn in through it, <0 fed out. */
export const LIVE_EXAMPLE_PAYLOAD = '{"meter_power_w": 1250, "production_w": 0, "consumption_w": 1250}'

/** Badge class per live state; one place for the live page, the metering-point lists and the setup cards. */
export const LIVE_STATE_BADGE_CLASS: Record<LiveState, string> = {
    fresh: 'badge badge-success',
    stale: 'badge badge-warning',
    never: 'badge badge-neutral',
}

/**
 * Whether history can be connected on a held metering point. With the live flag off the list only
 * holds behind-meter points and carries no capabilities, so an absent field means history; with it on
 * the list holds every held point and only those with the `history` capability qualify.
 */
export function historyEligible(point: Pick<EligibleMeteringPoint, 'eligible_capabilities'>): boolean {
    return !point.eligible_capabilities || point.eligible_capabilities.includes('history')
}

/** Whether live data can be connected on a held metering point (only while the live flag is on). */
export function liveEligible(point: Pick<EligibleMeteringPoint, 'eligible_capabilities'>): boolean {
    return !!point.eligible_capabilities?.includes('live')
}

/** Whether the point offers at least one capability to set up. */
export function hasCapability(point: Pick<EligibleMeteringPoint, 'eligible_capabilities'>): boolean {
    return historyEligible(point) || liveEligible(point)
}

type SourceLike = Pick<SupplementarySource, 'metering_point' | 'target' | 'zev' | 'provides_history' | 'provides_live'>

/** The source that provides `capability` on a metering point; sources are unique per capability and point. */
export function sourceFor<T extends SourceLike>(
    sources: T[] | undefined,
    meteringPointId: string,
    capability: Extract<SourceCapability, 'history' | 'live'>,
): T | undefined {
    return sources?.find((source) => source.metering_point === meteringPointId && (capability === 'history' ? source.provides_history : source.provides_live))
}

/** The ZEV's grid connection point source, if any. */
export function connectionPointSource<T extends SourceLike>(sources: T[] | undefined, zevId: string | undefined): T | undefined {
    return sources?.find((source) => source.target === 'connection_point' && source.zev === zevId)
}

/** Refresh everything a source change touches: the live view, the source lists, eligibility, the dashboard and the points' chips. */
export function invalidateSourceQueries(queryClient: QueryClient) {
    void queryClient.invalidateQueries({ queryKey: queryKeys.live.all })
    void queryClient.invalidateQueries({ queryKey: queryKeys.metering.supplementarySources() })
    void queryClient.invalidateQueries({ queryKey: queryKeys.metering.supplementaryEligible() })
    void queryClient.invalidateQueries({ queryKey: queryKeys.metering.supplementaryZevEligibleAll() })
    void queryClient.invalidateQueries({ queryKey: ['metering', 'dashboard-summary'] })
    // The status and live chips on the metering-point list come from the point itself.
    void queryClient.invalidateQueries({ queryKey: ['metering', 'points'] })
}

export const CSV_COLUMNS = ['timestamp', 'consumption_kwh', 'production_kwh', 'import_kwh', 'export_kwh'] as const

/**
 * Whether the energy-data feature is on, and which flagged meters the signed-in user holds.
 * `featureOn` is `false` while it is off (the endpoint answers 404), so callers can hide
 * every entry point with one check.
 */
export function useEnergyDataEligibility() {
    const query = useQuery({
        queryKey: queryKeys.metering.supplementaryEligible(),
        queryFn: fetchEligibleOrNull,
        staleTime: 60_000,
        retry: false,
    })
    const featureOn = query.data !== null && query.data !== undefined
    const eligible = query.data ?? []
    // With the live flag on `eligible` lists every held point; history means the behind-meter ones.
    const historyPoints = eligible.filter(historyEligible)
    const livePoints = eligible.filter(liveEligible)
    return {
        isLoading: query.isLoading,
        /** The check itself failed: neither "feature off" nor "nothing to connect" is known. */
        isError: query.isError,
        isFetching: query.isFetching,
        refetch: query.refetch,
        featureOn,
        eligible,
        /** Held points that can have a history source (behind the meter). */
        historyEligible: historyPoints,
        /** Held points that can have a live source (empty while the live flag is off). */
        liveEligible: livePoints,
        /** There is something to connect: the feature is on and the user holds a flagged meter. */
        canConnect: featureOn && historyPoints.length > 0,
    }
}
