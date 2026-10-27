import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faCircleCheck, faTriangleExclamation } from '@fortawesome/free-solid-svg-icons'
import { useTranslation } from 'react-i18next'
import { bandCoverage, type CoverageBand, type CoverageGap } from './bandCoverage'
import { bandName, bandWindow } from './bands'
import { kwhPrice } from './rateLines'
import { MONTH_KEYS, WEEKDAY_KEYS, formatSeason, formatWeekdays } from './recurrence'

type TariffBandCoverageProps = {
    bands: CoverageBand[]
    validity?: { valid_from?: string, valid_to?: string | null }
    /** Say so when every hour has a band; the form wants the reassurance, the pane only the problems. */
    showCovered?: boolean
}

/** Seconds into the day as `07:00`; the end of the day is `24:00`. */
const clock = (seconds: number) => [Math.floor(seconds / 3600), Math.floor(seconds / 60) % 60]
    .map((part) => String(part).padStart(2, '0')).join(':')

/**
 * Whether a version's bands leave hours to the fallback, or match some hour
 * twice, said in the user's words: which months, days and hours, and what
 * those hours are priced at instead.
 */
export function TariffBandCoverage({ bands, validity, showCovered = false }: TariffBandCoverageProps) {
    const { t } = useTranslation()
    if (bands.length === 0) return null
    const { uncovered, overlaps, gaps, fallbacks } = bandCoverage(bands, validity)
    if (!uncovered && !overlaps) {
        return showCovered ? (
            <p className="tariff-band-coverage is-covered grid-span-full" role="status">
                <FontAwesomeIcon icon={faCircleCheck} fixedWidth aria-hidden="true" />
                {t('pages.tariffs.coverage.covered')}
            </p>
        ) : null
    }

    const monthNames = MONTH_KEYS.map((key) => t(`pages.tariffs.monthsShort.${key}` as Parameters<typeof t>[0]))
    const dayNames = WEEKDAY_KEYS.map((key) => t(`pages.tariffs.weekdaysShort.${key}` as Parameters<typeof t>[0]))

    // The same days and season are one phrase: `07:00–21:00 · Sat–Sun · Nov–Mar`.
    // Every day and every month are left out: no qualifier means no restriction.
    function describe(months?: number[]) {
        const phrases = new Map<string, string[]>()
        for (const gap of gaps as CoverageGap[]) {
            const shared = gap.months.filter((month) => !months || months.includes(month))
            if (shared.length === 0) continue
            const when = [formatWeekdays(gap.weekdays.join(','), dayNames), formatSeason(shared.join(','), monthNames)].filter(Boolean).join(' · ')
            phrases.set(when, [...(phrases.get(when) ?? []), `${clock(gap.start)}–${clock(gap.end)}`])
        }
        return [...phrases].map(([when, times]) => [times.join(', '), when].filter(Boolean).join(' · ')).join('; ')
    }

    function priceOf(band: CoverageBand) {
        if (band.percentage != null && band.percentage !== '') return t('pages.tariffs.rateCard.percentOf', { percentage: Number(band.percentage) })
        return band.price_chf_per_kwh ? `${kwhPrice.format(Number(band.price_chf_per_kwh))} ${t('pages.tariffs.chfPerKwh')}` : '—'
    }

    return (
        <div className="tariff-band-coverage is-warning grid-span-full" role="status">
            <FontAwesomeIcon icon={faTriangleExclamation} fixedWidth aria-hidden="true" />
            <div>
                {fallbacks.map(({ band, months }, index) => {
                    const name = bandName(band, t(`pages.tariffs.periodTypes.${band.period_type}` as Parameters<typeof t>[0]))
                    const window = bandWindow(band)
                    return (
                        <p key={index}>
                            {t('pages.tariffs.coverage.fallback', {
                                schedule: describe(months),
                                band: [name, name !== window && window].filter(Boolean).join(' '),
                                price: priceOf(band),
                            })}
                        </p>
                    )
                })}
                {overlaps && <p>{t('pages.tariffs.coverage.overlaps')}</p>}
            </div>
        </div>
    )
}
