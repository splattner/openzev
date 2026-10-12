import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faChevronRight, faTriangleExclamation } from '@fortawesome/free-solid-svg-icons'
import { useTranslation } from 'react-i18next'
import { formatShortDate } from '../../lib/appSettings'
import { todayBusinessIso } from '../../lib/dates'
import type { AppSettings, Tariff, TariffSeries } from '../../types/api'
import { seriesKeyOf, useTariffDisplay } from './useTariffDisplay'
import { listedVersion, validityState } from './validity'
import { emphasizedDate } from './datePresentation'

const DATE_SLOT = '\u0000'

type TariffSeriesSection = {
    category: Tariff['category']
    series: TariffSeries[]
}

type TariffCategorySectionsProps = {
    tariffSections: TariffSeriesSection[]
    settings: AppSettings
    /** The series currently shown in the detail drawer, so its row can be highlighted. */
    openSeriesKey: string | null
    /** The Upcoming view: each row shows its series' next version. */
    upcoming?: boolean
    /** Open the exact version displayed by the row. */
    onOpenDetail: (series: TariffSeries, versionId: string) => void
}

/**
 * One row per tariff series; details and write actions live in the drawer.
 */
export function TariffCategorySections({
    tariffSections,
    settings,
    openSeriesKey,
    upcoming = false,
    onOpenDetail,
}: TariffCategorySectionsProps) {
    const { t } = useTranslation()
    const today = todayBusinessIso()
    const { sourceById, validityBadge, rateLines, pricingTooltipFor } = useTariffDisplay(settings, today)

    // `ab 01.01.2027`, the year (and, within this year, the month) bold. The
    // sentence is cut at its date, so each language keeps its own word order.
    function upcomingStart(validFrom: string) {
        const [before, after] = t('pages.tariffs.validity.starts', { date: DATE_SLOT }).split(DATE_SLOT)
        const parts = emphasizedDate(formatShortDate(validFrom, settings), settings.date_format_short, validFrom.slice(0, 4) === today.slice(0, 4))
        return <>{before}{parts.map((part, index) => (part.strong ? <strong key={index}>{part.text}</strong> : part.text))}{after}</>
    }

    return (
        <section className="card tariff-list">
            {tariffSections.map((section) => (
                <table key={section.category} className="tariff-table">
                    <thead>
                        <tr>
                            <th scope="col">
                                {t(`pages.tariffs.categories.${section.category}` as Parameters<typeof t>[0])}
                            </th>
                            <th scope="col" className="tariff-table-applies">{t('pages.tariffs.rateCard.applies')}</th>
                            <th scope="col" className="numeric">{t('pages.tariffs.rateCard.price')}</th>
                            <th scope="col" className="tariff-table-unit">{t('pages.tariffs.rateCard.unit')}</th>
                            <th scope="col" id={`tariff-bands-${section.category}`} className="tariff-table-bands">
                                <span className="visually-hidden">
                                    {t('pages.tariffs.rateCard.applies')} · {t('pages.tariffs.rateCard.price')} · {t('pages.tariffs.rateCard.unit')}
                                </span>
                            </th>
                            <th scope="col" className="tariff-table-valid">{t('pages.tariffs.rateCard.valid')}</th>
                            <th scope="col" className="tariff-table-open">
                                <span className="visually-hidden">{t('pages.tariffs.viewDetails')}</span>
                            </th>
                        </tr>
                    </thead>
                    <tbody>
                        {section.series.map((series) => {
                            const seriesKey = seriesKeyOf(series)
                            const shown = listedVersion(series.versions, today, upcoming)
                            const state = validityState(shown, today)

                            const dynamicSource = shown.dynamic_source ? sourceById.get(shown.dynamic_source) : undefined
                            const fetchFailed = dynamicSource?.last_fetch_status === 'failed'
                            const lines = rateLines(series, shown)
                            const pricingExplanation = pricingTooltipFor(series, shown, dynamicSource)
                            const badge = validityBadge(shown)
                            const notes = shown.notes?.trim()
                            const isOpen = seriesKey === openSeriesKey
                            function openRow() {
                                onOpenDetail(series, shown.id)
                            }

                            return (
                                <tr
                                    key={seriesKey}
                                    className={[isOpen && 'is-selected', state === 'expired' && 'is-ended'].filter(Boolean).join(' ') || undefined}
                                    onClick={openRow}
                                >
                                    <td className="tariff-table-tariff">
                                        <div className="tariff-table-name">
                                            <button
                                                type="button"
                                                className="tariff-select"
                                                aria-expanded={isOpen}
                                                onClick={(event) => {
                                                    event.stopPropagation()
                                                    openRow()
                                                }}
                                            >
                                                {series.name}
                                            </button>
                                            {series.gaps.length > 0 && (
                                                <span className="badge badge-danger" title={t('pages.tariffs.versions.gapTooltip')}>
                                                    <FontAwesomeIcon icon={faTriangleExclamation} fixedWidth />{' '}
                                                    {t('pages.tariffs.versions.gapBadge', { count: series.gaps.length })}
                                                </span>
                                            )}
                                            {fetchFailed && (
                                                <span
                                                    className="badge badge-danger"
                                                    title={t('pages.tariffs.dynamicFetchFailedTooltip', { error: dynamicSource.last_fetch_error })}
                                                >
                                                    <FontAwesomeIcon icon={faTriangleExclamation} fixedWidth />{' '}
                                                    {t('pages.tariffs.dynamicFetchFailed')}
                                                </span>
                                            )}
                                        </div>
                                        {series.energy_type && (
                                            <div className="tariff-table-meta">
                                                {t(`pages.tariffs.energyTypes.${series.energy_type}` as Parameters<typeof t>[0])}
                                            </div>
                                        )}
                                        {notes && <div className="tariff-table-notes" title={notes}>{notes}</div>}
                                    </td>
                                    <td className="tariff-table-lines tariff-table-applies">
                                        {lines.map((line, index) => <div key={index} title={line.applies}>{line.applies}</div>)}
                                    </td>
                                    <td className="tariff-table-lines numeric" title={pricingExplanation}>
                                        {lines.map((line, index) => <div key={index}>{line.price}</div>)}
                                    </td>
                                    <td className="tariff-table-lines tariff-table-unit">
                                        {lines.map((line, index) => <div key={index} title={line.unit}>{line.unit}</div>)}
                                    </td>
                                    <td className="tariff-table-bands" headers={`tariff-bands-${section.category}`}>
                                        {lines.map((line, index) => (
                                            <div key={index} className="tariff-table-band" title={pricingExplanation ?? line.applies}>
                                                <span className="tariff-table-band-applies">{line.applies}</span>
                                                {line.price && (
                                                    <span className="tariff-table-band-price">
                                                        {line.price} CHF{line.unit ? ` ${line.unit}` : ''}
                                                    </span>
                                                )}
                                            </div>
                                        ))}
                                    </td>
                                    <td className="tariff-table-valid">
                                        {state === 'scheduled'
                                            ? upcomingStart(shown.valid_from)
                                            : <span title={badge.tooltip}>{badge.label}</span>}
                                    </td>
                                    <td className="tariff-table-open">
                                        <FontAwesomeIcon icon={faChevronRight} fixedWidth />
                                    </td>
                                </tr>
                            )
                        })}
                    </tbody>
                </table>
            ))}
        </section>
    )
}
