import { useQuery } from '@tanstack/react-query'
import { API_BASE_URL } from './api/client'
import { queryKeys } from './api/queryKeys'
import { fetchEligibleOrNull } from './api/supplementary'
import type { GrossEnergy, SupplementaryStatus } from '../types/api'

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
    return {
        isLoading: query.isLoading,
        featureOn,
        eligible,
        /** The Account tab is worth showing: the feature is on and the user holds a flagged meter. */
        tabAvailable: featureOn && eligible.length > 0,
    }
}
