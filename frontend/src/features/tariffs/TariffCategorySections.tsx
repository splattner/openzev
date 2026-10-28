import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faChevronRight, faClock, faTriangleExclamation } from '@fortawesome/free-solid-svg-icons'
import { useTranslation } from 'react-i18next'
import { formatShortDate } from '../../lib/appSettings'
import { todayBusinessIso } from '../../lib/dates'
import type { AppSettings, Tariff, TariffSeries } from '../../types/api'
import { seriesKeyOf, useTariffDisplay } from './useTariffDisplay'
import type { TariffOverviewRow } from './validity'
import { emphasizedDate } from './datePresentation'
import { nextChange } from './rateLines'
import { deltaSummary } from './priceDelta'
import { bandCoverage } from './bandCoverage'
import { TariffTypeIcon } from './TariffTypeIcon'

const DATE_SLOT = '\u0000'

const categoryOrder: Tariff['category'][] = ['energy', 'grid_fees', 'levies', 'metering']

/** What a group of rows is about; it decides how a row words its validity. */
export type TariffRowsKind = 'current' | 'upcoming' | 'history'

type TariffCategorySectionsProps = {
    rows: TariffOverviewRow[]
    kind: TariffRowsKind
    settings: AppSettings
    /** The series and version shown in the detail pane, so its row can be highlighted. */
    selected: { seriesKey: string, versionId: string } | null
    /** Open the exact version displayed by the row. */
    onOpenDetail: (series: TariffSeries, versionId: string) => void
}

/**
 * One row per tariff series and group, in the category order; details and
 * write actions live in the detail pane.
 */
export function TariffCategorySections({
    rows,
    kind,
    settings,
    selected,
    onOpenDetail,
}: TariffCategorySectionsProps) {
    const { t } = useTranslation()
    const today = todayBusinessIso()
    const { sourceById, validityBadge, rateLines, pricingTooltipFor } = useTariffDisplay(settings, today)
    const tariffSections = categoryOrder
        .map((category) => ({ category, rows: rows.filter((row) => row.series.category === category) }))
        .filter((section) => section.rows.length > 0)

    // `ab 01.01.2027`, the year (and, within this year, the month) bold. The
    // sentence is cut at its date, so each language keeps its own word order.
    function upcomingStart(validFrom: string) {
        const [before, after] = t('pages.tariffs.validity.starts', { date: DATE_SLOT }).split(DATE_SLOT)
        const parts = emphasizedDate(formatShortDate(validFrom, settings), settings.date_format_short, validFrom.slice(0, 4) === today.slice(0, 4))
        return <>{before}{parts.map((part, index) => (part.strong ? <strong key={index}>{part.text}</strong> : part.text))}{after}</>
    }

    return (
        <div className="table-card invoice-rows tariff-list">
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
                            <th scope="col" id={`tariff-bands-${kind}-${section.category}`} className="tariff-table-bands">
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
                        {section.rows.map(({ series, version: shown, upcomingVersion }) => {
                            const seriesKey = seriesKeyOf(series)

                            const dynamicSource = shown.dynamic_source ? sourceById.get(shown.dynamic_source) : undefined
                            const fetchFailed = dynamicSource?.last_fetch_status === 'failed'
                            const lines = rateLines(series, shown)
                            const pricingExplanation = pricingTooltipFor(series, shown, dynamicSource)
                            const badge = validityBadge(shown)
                            const notes = shown.notes?.trim()
                            const isOpen = seriesKey === selected?.seriesKey
                                && (shown.id === selected.versionId || upcomingVersion?.id === selected.versionId)
                            // Only a row about now or later: an ended version's holes are history.
                            const hasUncoveredHours = kind !== 'history' && !shown.dynamic_source
                                && (series.billing_mode === 'energy' || series.billing_mode === 'percentage_of_energy')
                                && shown.periods.length > 0 && bandCoverage(shown.periods, shown).uncovered
                            const change = upcomingVersion ? nextChange(lines, rateLines(series, upcomingVersion)) : null
                            const changeSummary = upcomingVersion && change?.kind === 'prices'
                                ? deltaSummary(series, shown, upcomingVersion, (diff) => t('pages.tariffs.change.points', { diff }))
                                : null
                            const changeDate = upcomingVersion ? formatShortDate(upcomingVersion.valid_from, settings) : ''
                            function openRow() {
                                onOpenDetail(series, shown.id)
                            }

                            return (
                                <tr
                                    key={`${seriesKey}:${shown.id}`}
                                    data-row-key={`${seriesKey}:${shown.id}`}
                                    className={[isOpen && 'is-selected', kind === 'history' && 'is-ended'].filter(Boolean).join(' ') || undefined}
                                    onClick={openRow}
                                >
                                    <td className="tariff-table-tariff">
                                        <div className="tariff-table-name">
                                            <TariffTypeIcon type={series.energy_type} />
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
                                            {hasUncoveredHours && (
                                                <span className="badge badge-danger" title={t('pages.tariffs.coverage.badgeTooltip')}>
                                                    <FontAwesomeIcon icon={faTriangleExclamation} fixedWidth />{' '}
                                                    {t('pages.tariffs.coverage.badge')}
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
                                    <td className="tariff-table-bands" headers={`tariff-bands-${kind}-${section.category}`}>
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
                                        {kind === 'upcoming'
                                            ? upcomingStart(shown.valid_from)
                                            : kind === 'history'
                                                ? <span>{formatShortDate(shown.valid_from, settings)} – {formatShortDate(shown.valid_to ?? shown.valid_from, settings)}</span>
                                                : <span title={badge.tooltip}>{badge.label}</span>}
                                        {upcomingVersion && change && (
                                            <button
                                                type="button"
                                                className="tariff-next-change"
                                                onClick={(event) => {
                                                    event.stopPropagation()
                                                    onOpenDetail(series, upcomingVersion.id)
                                                }}
                                            >
                                                <FontAwesomeIcon icon={faClock} fixedWidth aria-hidden="true" />
                                                {change.kind === 'prices'
                                                    ? t(changeSummary ? 'pages.tariffs.overview.nextPricesChange' : 'pages.tariffs.overview.nextPrices', { date: changeDate, prices: change.prices, unit: change.unit, change: changeSummary })
                                                    : t(change.kind === 'schedule' ? 'pages.tariffs.overview.nextSchedule' : 'pages.tariffs.overview.nextVersion', { date: changeDate })}
                                            </button>
                                        )}
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
        </div>
    )
}
