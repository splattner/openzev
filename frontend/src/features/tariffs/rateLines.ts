import type { TariffSeries, TariffVersion } from '../../types/api'
import { bandName, bandWindow } from './bands'
import { formatSeason, formatWeekdays } from './recurrence'

export type RateLine = { applies: string, price: string, unit: string }

/** Minimal translate signature used by the pure formatter (subset of i18next). */
export type RateLineTranslate = (key: string, opts?: Record<string, unknown>) => string

// At least three decimals, so 0.18 lines up with 0.085; the API's five would
// read 0.29500.
export const kwhPrice = new Intl.NumberFormat('en-US', { minimumFractionDigits: 3, maximumFractionDigits: 5, useGrouping: false })

/** When a band applies, as the tariff overview PDF names it:
 * `High (HT) Mon–Fri, 07:00–21:00`. A non-flat band without a window prices
 * every hour the others leave open, so it reads `Low (NT) all other hours`;
 * an unnamed time band is called "all other hours" outright. */
export function formatBandApplies(
    period: TariffVersion['periods'][number],
    t: RateLineTranslate,
    dayNames: string[],
    monthNames: string[],
): string {
    const window = bandWindow(period)
    const catchAll = period.period_type !== 'flat' && !window
    const allOtherHours = t('pages.tariffs.rateCard.allOtherHours')
    const unnamedCatchAll = catchAll && period.period_type === 'band' && !period.label
    const name = unnamedCatchAll
        ? allOtherHours
        : bandName(period, t(`pages.tariffs.periodTypes.${period.period_type}`, { defaultValue: period.period_type }))
    const when = [
        formatWeekdays(period.weekdays, dayNames),
        name === window ? null : window,
        formatSeason(period.months, monthNames),
        catchAll && !unnamedCatchAll && allOtherHours,
    ].filter(Boolean).join(', ')
    if (period.period_type === 'flat' && !when) return t('pages.tariffs.rateCard.allHours')
    return `${name} ${when}`.trim()
}

/** When a band applies, as the pane and the band editor say it: hours,
 * weekdays, and the months if the band is restricted to some.
 * `07:00–21:00 · Mon–Fri`, `all other hours · every day`. Hours and days
 * use the same helpers as the list, so they read alike and never as raw
 * `07:00:00` / `0,1,2,3,4`. */
export function formatBandSchedule(
    period: Pick<TariffVersion['periods'][number], 'period_type' | 'time_from' | 'time_to' | 'weekdays' | 'months'>,
    t: RateLineTranslate,
    dayNames: string[],
    monthNames: string[],
): string {
    const hours = period.period_type === 'flat'
        ? t('pages.tariffs.allDay')
        : bandWindow(period) ?? t('pages.tariffs.rateCard.allOtherHours')
    return [
        hours,
        formatWeekdays(period.weekdays, dayNames) || t('pages.tariffs.allWeekdays'),
        formatSeason(period.months, monthNames),
    ].filter(Boolean).join(' · ')
}

/** Display rows for tariff bands, dynamic averages, or fixed fees. */
export function buildRateLines(
    series: TariffSeries,
    version: TariffVersion,
    t: RateLineTranslate,
    dayNames: string[],
    monthNames: string[],
    formatDate: (isoDate: string) => string,
): RateLine[] {
    const perKwh = t('pages.tariffs.rateCard.perKwh')
    if (version.dynamic_source) {
        const summary = version.dynamic_price_summary
        if (!summary?.average_chf_per_kwh) return [{ applies: t('pages.tariffs.dynamicPriced'), price: '—', unit: perKwh }]
        // The average covers a window ending today, not the version's validity.
        return [{
            applies: t(summary.status === 'partial' ? 'pages.tariffs.rateCard.dynamicPartial' : 'pages.tariffs.rateCard.dynamicAverage', {
                from: summary.reference_from ? formatDate(summary.reference_from) : '',
                to: summary.reference_to ? formatDate(summary.reference_to) : '',
            }),
            price: Number(summary.average_chf_per_kwh).toFixed(3),
            unit: perKwh,
        }]
    }
    if (series.billing_mode === 'energy' || series.billing_mode === 'percentage_of_energy') {
        if (!version.periods.length) return [{ applies: t('pages.tariffs.noPeriods'), price: '', unit: '' }]
        const base = version.percentage_base_summary?.price_chf_per_kwh
        return version.periods.map((period) => {
            const applies = formatBandApplies(period, t, dayNames, monthNames)
            if (series.billing_mode === 'energy') {
                return { applies, price: period.price_chf_per_kwh ? kwhPrice.format(Number(period.price_chf_per_kwh)) : '—', unit: perKwh }
            }
            const percentage = Number(period.percentage)
            const share = base != null
                ? t('pages.tariffs.rateCard.percentOfBase', { percentage, base: Number(base).toFixed(3) })
                : t('pages.tariffs.rateCard.percentOf', { percentage })
            return {
                applies: [applies, share, version.percentage_base_summary?.dynamic_status === 'partial'
                    && t('pages.tariffs.rateCard.incompleteBaseAverage')].filter(Boolean).join(' · '),
                price: base != null ? `≈ ${(Number(base) * percentage / 100).toFixed(3)}` : '—',
                unit: perKwh,
            }
        })
    }
    const yearly = series.billing_mode.endsWith('yearly_fee')
    const basis = series.billing_mode.startsWith('per_metering_point')
        ? 'perMeteringPoint'
        : series.billing_mode.startsWith('shared') ? 'shared' : 'perParticipant'
    return [{
        applies: t(`pages.tariffs.rateCard.${basis}`),
        price: Number(version.fixed_price_chf || 0).toFixed(2),
        unit: t(yearly ? 'pages.tariffs.rateCard.perYear' : 'pages.tariffs.rateCard.perMonth'),
    }]
}

/** How the next version of a tariff differs from the one in force, as a row says it. */
export type NextChange =
    | { kind: 'prices', prices: string, unit: string }
    | { kind: 'schedule' }
    | { kind: 'version' }

const hasPrice = (line: RateLine) => Boolean(line.price) && line.price !== '—'

/**
 * Same bands (the same hours, in the same order) at new prices: the new
 * prices, to read against the current ones. Different bands: say that the
 * schedule changes rather than line up two lists that do not match. A next
 * version with no prices to show (a dynamic one, or no bands yet) is just a
 * date.
 */
export function nextChange(current: RateLine[], planned: RateLine[]): NextChange {
    if (!planned.some(hasPrice)) return { kind: 'version' }
    const comparable = current.length === planned.length
        && current.every((line, index) => line.applies === planned[index].applies && line.unit === planned[index].unit)
    if (!comparable) return { kind: 'schedule' }
    return { kind: 'prices', prices: planned.map((line) => line.price || '—').join(' / '), unit: planned[0].unit }
}
