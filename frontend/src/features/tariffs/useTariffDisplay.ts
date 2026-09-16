import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { fetchDynamicTariffSources } from '../../lib/api/tariffs'
import { queryKeys } from '../../lib/api/queryKeys'
import { formatShortDate } from '../../lib/appSettings'
import type { AppSettings, DynamicTariffSource, Tariff, TariffSeries, TariffVersion } from '../../types/api'
import { validityState, type ValidityState } from './validity'

// Amber rather than blue for scheduled: blue is already the billing-mode badge
// sitting right next to it, and two adjacent blue badges read as one group.
export const VALIDITY_BADGE_CLASS: Record<ValidityState, string> = {
    active: 'badge badge-success',
    scheduled: 'badge badge-warning',
    expired: 'badge badge-neutral',
}

/**
 * Pricing/validity display logic shared by the tariff card list and the
 * detail drawer, so the two views can never drift into describing the same
 * version differently. Also owns the dynamic-sources lookup both need —
 * they share its query key, so mounting both costs one request, not two.
 */
export function useTariffDisplay(settings: AppSettings, today: string) {
    const { t } = useTranslation()

    const sourcesQuery = useQuery({
        queryKey: queryKeys.tariffs.dynamicSources(),
        queryFn: fetchDynamicTariffSources,
        staleTime: 5 * 60 * 1000,
    })
    const sourceById = new Map((sourcesQuery.data ?? []).map((source) => [source.id, source]))

    function validityBadge(version: Tariff) {
        const state = validityState(version, today)
        const validFrom = formatShortDate(version.valid_from, settings)
        const validTo = version.valid_to ? formatShortDate(version.valid_to, settings) : null
        const label = state === 'scheduled'
            ? t('pages.tariffs.validity.starts', { date: validFrom })
            : state === 'expired'
                ? t('pages.tariffs.validity.ended', { date: validTo })
                : validTo
                    ? t('pages.tariffs.validity.until', { date: validTo })
                    : t('pages.tariffs.validity.since', { date: validFrom })
        return {
            className: VALIDITY_BADGE_CLASS[state],
            label,
            tooltip: `${validFrom} - ${validTo ?? t('pages.tariffs.openEnded')}`,
        }
    }

    /** A one-line price summary for a version, whatever it is priced by.
     *
     * `dynamic_source` is checked before `billing_mode`, not alongside it: a
     * dynamic tariff is still `billing_mode = 'energy'`, but carries no
     * periods at all — its price lives in the fetched series, not on this
     * version — so falling into the ordinary energy branch below would
     * always read "no bands configured" for one.
     */
    function priceSummary(series: TariffSeries, version: TariffVersion): string {
        if (version.dynamic_source) {
            const source = sourceById.get(version.dynamic_source)
            const summary = version.dynamic_price_summary
            const sourceLabel = source
                ? t('pages.tariffs.dynamicPricedFrom', { label: source.label })
                : t('pages.tariffs.dynamicPriced')
            const minimumSuffix = version.minimum_price_chf_per_kwh
                ? ` · ${t('pages.tariffs.dynamicMinimum', { price: Number(version.minimum_price_chf_per_kwh).toFixed(3) })}`
                : ''
            if (summary?.average_chf_per_kwh) {
                return `${sourceLabel} · ${t(
                    summary.status === 'partial'
                        ? 'pages.tariffs.dynamicAveragePartial'
                        : 'pages.tariffs.dynamicAverage',
                    { price: Number(summary.average_chf_per_kwh).toFixed(3) },
                )}${minimumSuffix}`
            }
            return `${sourceLabel} · ${t('pages.tariffs.dynamicPriceUnavailable')}${minimumSuffix}`
        }
        if (series.billing_mode === 'energy') {
            const prices = version.periods.map((period) => `${period.price_chf_per_kwh}`)
            return prices.length
                ? `CHF ${prices.join(' / ')}/kWh`
                : t('pages.tariffs.noPeriods')
        }
        if (series.billing_mode === 'percentage_of_energy') {
            return `${version.percentage ?? '0'}%`
        }
        return `CHF ${version.fixed_price_chf || '0.00'}`
    }

    function pricingLabelFor(series: TariffSeries, version: TariffVersion) {
        if (version.dynamic_source) return priceSummary(series, version)
        const energy = t(`pages.tariffs.energyTypes.${series.energy_type || 'local'}`)
        if (series.billing_mode === 'energy') return energy
        if (series.billing_mode !== 'percentage_of_energy') return `CHF ${version.fixed_price_chf || '0.00'}`
        const label = `${version.percentage ?? '0'}% · ${energy}`
        const base = version.percentage_base_summary
        if (base?.price_chf_per_kwh != null) {
            const price = (Number(base.price_chf_per_kwh) * Number(version.percentage ?? 0) / 100).toFixed(3)
            return `${label} · ${t('pages.tariffs.approxPrice', { price })}`
        }
        if (base?.dynamic_status === 'unavailable') return `${label} · ${t('pages.tariffs.dynamicBaseUnavailable')}`
        return label
    }

    function pricingTooltipFor(series: TariffSeries, version: TariffVersion, source?: DynamicTariffSource) {
        if (version.dynamic_source) {
            if (source?.last_fetch_status === 'failed') {
                return t('pages.tariffs.dynamicFetchFailedTooltip', { error: source.last_fetch_error })
            }
            if (version.dynamic_price_summary?.status === 'partial') return t('pages.tariffs.dynamicAveragePartialTooltip')
            if (version.dynamic_price_summary?.status === 'complete') return t('pages.tariffs.dynamicAverageTooltip')
            return t('pages.tariffs.dynamicPriceUnavailableTooltip')
        }
        if (series.billing_mode !== 'percentage_of_energy') return undefined
        const base = version.percentage_base_summary
        if (base?.dynamic_status === 'unavailable') return t('pages.tariffs.dynamicBaseUnavailableTooltip')
        if (base?.price_chf_per_kwh != null) {
            const basePrice = Number(base.price_chf_per_kwh)
            const explanation = t('pages.tariffs.approxPriceTooltip', {
                percentage: version.percentage ?? '0', basePrice: basePrice.toFixed(3),
                effectivePrice: (basePrice * Number(version.percentage ?? 0) / 100).toFixed(3),
            })
            if (base.dynamic_status === 'partial') return `${explanation} ${t('pages.tariffs.dynamicAveragePartialTooltip')}`
            if (base.dynamic_status === 'complete') return `${explanation} ${t('pages.tariffs.dynamicAverageTooltip')}`
            return explanation
        }
        return undefined
    }

    return { sourceById, validityBadge, priceSummary, pricingLabelFor, pricingTooltipFor }
}

/** Stable identity for a series, independent of any one version — used to key
 * UI state and the `?tariff=` URL parameter. */
export function seriesKeyOf(series: Pick<TariffSeries, 'zev' | 'name'>): string {
    return `${series.zev}:${series.name}`
}
