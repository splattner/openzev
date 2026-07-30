import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import {
    faChevronDown,
    faChevronUp,
    faClone,
    faLayerGroup,
    faPen,
    faPlus,
    faTag,
    faTrash,
    faTriangleExclamation,
} from '@fortawesome/free-solid-svg-icons'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { formatShortDate } from '../../lib/appSettings'
import type {
    AppSettings,
    Tariff,
    TariffPeriod,
    TariffSeries,
    TariffVersion,
} from '../../types/api'
import { todayIso, validityState, type ValidityState } from './validity'
import { TariffPriceHistoryChart } from './TariffPriceHistoryChart'

type TariffSeriesSection = {
    category: Tariff['category']
    series: TariffSeries[]
}

// Amber rather than blue for scheduled: blue is already the billing-mode badge
// sitting right next to it, and two adjacent blue badges read as one group.
const VALIDITY_BADGE_CLASS: Record<ValidityState, string> = {
    active: 'badge badge-success',
    scheduled: 'badge badge-warning',
    expired: 'badge badge-neutral',
}

type TariffCategorySectionsProps = {
    tariffSections: TariffSeriesSection[]
    /** Every series in scope — percentage tariffs derive their price from the grid ones. */
    allSeries: TariffSeries[]
    percentageBasePricing: Map<string, number>
    settings: AppSettings
    deleteTariffDisabled: boolean
    deletePeriodDisabled: boolean
    onEditTariff: (tariff: Tariff) => void
    onDeleteTariff: (tariff: Tariff) => void
    onOpenCreatePeriodModal: (tariffId: string) => void
    onEditPeriod: (period: TariffPeriod) => void
    onDeletePeriod: (period: TariffPeriod) => void
    onNewVersion: (series: TariffSeries, source: TariffVersion) => void
    onDuplicate: (series: TariffSeries, source: TariffVersion) => void
    onRenameSeries: (series: TariffSeries, source: TariffVersion) => void
}

export function TariffCategorySections({
    tariffSections,
    allSeries,
    percentageBasePricing,
    settings,
    deleteTariffDisabled,
    deletePeriodDisabled,
    onEditTariff,
    onDeleteTariff,
    onOpenCreatePeriodModal,
    onEditPeriod,
    onDeletePeriod,
    onNewVersion,
    onDuplicate,
    onRenameSeries,
}: TariffCategorySectionsProps) {
    const { t } = useTranslation()
    const [expandedSeries, setExpandedSeries] = useState<Set<string>>(new Set())
    // Which version a card is showing. Defaults to the active one, so a card
    // reads as "what this tariff costs now" until you deliberately look back.
    const [shownVersionBySeries, setShownVersionBySeries] = useState<Record<string, string>>({})
    const today = todayIso()

    const toggleExpanded = (key: string) => {
        setExpandedSeries((current) => {
            const next = new Set(current)
            if (next.has(key)) {
                next.delete(key)
            } else {
                next.add(key)
            }
            return next
        })
    }

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

    /** A one-line price summary for a version, whatever it is priced by. */
    function priceSummary(series: TariffSeries, version: TariffVersion): string {
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

    return (
        <div className="tariff-category-sections">
            {tariffSections.map((section) => (
                <section
                    key={section.category}
                    className={`tariff-category-section tariff-category-section-${section.category.replace(/_/g, '-')}`}
                >
                    <div className="tariff-category-header">
                        <div className="tariff-category-title-row">
                            <h3>{t(`pages.tariffs.categories.${section.category}` as Parameters<typeof t>[0])}</h3>
                            <span className="badge badge-neutral">{section.series.length}</span>
                        </div>
                    </div>

                    <div className="tariff-card-list">
                        {section.series.map((series) => {
                            const seriesKey = `${series.zev}:${series.name}`
                            const versions = series.versions
                            const shownId = shownVersionBySeries[seriesKey]
                                ?? series.active_version_id
                                ?? versions[0].id
                            const shown = versions.find((version) => version.id === shownId) ?? versions[0]
                            const isShowingActive = shown.id === series.active_version_id

                            const usesPeriods = series.billing_mode === 'energy'
                            const shownPeriods = shown.periods
                            const energyTypeLabel = t(`pages.tariffs.energyTypes.${series.energy_type || 'local'}` as Parameters<typeof t>[0])
                            const basePrice = percentageBasePricing.get(shown.id)
                            const pricingLabel = series.billing_mode === 'energy'
                                ? energyTypeLabel
                                : series.billing_mode === 'percentage_of_energy'
                                    ? basePrice
                                        ? `${shown.percentage ?? '0'}% · ${energyTypeLabel} · ${t('pages.tariffs.approxPrice', { price: (basePrice * Number(shown.percentage ?? 0) / 100).toFixed(3) })}`
                                        : `${shown.percentage ?? '0'}% · ${energyTypeLabel}`
                                    : `CHF ${shown.fixed_price_chf || '0.00'}`
                            const pricingTooltip = series.billing_mode === 'percentage_of_energy' && basePrice
                                ? t('pages.tariffs.approxPriceTooltip', {
                                    percentage: shown.percentage ?? '0',
                                    basePrice: basePrice.toFixed(3),
                                    effectivePrice: (basePrice * Number(shown.percentage ?? 0) / 100).toFixed(3),
                                })
                                : undefined
                            const notes = shown.notes?.trim()
                            const isExpanded = expandedSeries.has(seriesKey)
                            const badge = validityBadge(shown)

                            return (
                                <article key={seriesKey} className="tariff-card">
                                    <div className="tariff-card-header">
                                        <div className="tariff-card-title">
                                            <div className="tariff-card-heading">
                                                <strong>{series.name}</strong>
                                                <div className="tariff-name-badges">
                                                    <span className="badge badge-info">
                                                        {t(`pages.tariffs.billingModes.${series.billing_mode}` as Parameters<typeof t>[0], { defaultValue: series.billing_mode })}
                                                    </span>
                                                    {series.energy_type && (
                                                        <span className="badge badge-success">
                                                            {t(`pages.tariffs.energyTypes.${series.energy_type}` as Parameters<typeof t>[0])}
                                                        </span>
                                                    )}
                                                    <span className={badge.className} title={badge.tooltip}>
                                                        {badge.label}
                                                    </span>
                                                    {series.version_count > 1 && (
                                                        <span
                                                            className="badge badge-neutral"
                                                            title={t('pages.tariffs.versions.countTooltip')}
                                                        >
                                                            <FontAwesomeIcon icon={faLayerGroup} fixedWidth />{' '}
                                                            {t('pages.tariffs.versions.count', { count: series.version_count })}
                                                        </span>
                                                    )}
                                                    {series.gaps.length > 0 && (
                                                        <span
                                                            className="badge badge-danger"
                                                            title={t('pages.tariffs.versions.gapTooltip')}
                                                        >
                                                            <FontAwesomeIcon icon={faTriangleExclamation} fixedWidth />{' '}
                                                            {t('pages.tariffs.versions.gapBadge', { count: series.gaps.length })}
                                                        </span>
                                                    )}
                                                </div>
                                            </div>
                                        </div>

                                        <div className="tariff-card-actions">
                                            <button
                                                className="button button-primary button-compact"
                                                type="button"
                                                onClick={() => onNewVersion(series, shown)}
                                            >
                                                <FontAwesomeIcon icon={faPlus} fixedWidth />
                                                {t('pages.tariffs.versions.newVersion')}
                                            </button>
                                            <button className="button button-secondary button-compact" type="button" onClick={() => onEditTariff(shown)}>
                                                <FontAwesomeIcon icon={faPen} fixedWidth />
                                                {t('common.edit')}
                                            </button>
                                            <button
                                                className="button button-secondary button-compact"
                                                type="button"
                                                aria-expanded={isExpanded}
                                                onClick={() => toggleExpanded(seriesKey)}
                                            >
                                                <FontAwesomeIcon icon={isExpanded ? faChevronUp : faChevronDown} fixedWidth />
                                                {isExpanded ? t('common.hideDetails') : t('common.showDetails')}
                                            </button>
                                        </div>
                                    </div>

                                    <div className="tariff-card-summary-row">
                                        {!usesPeriods && (
                                            <div className="tariff-detail-card">
                                                <span className="tariff-detail-label">{t('pages.tariffs.col.pricing')}</span>
                                                <span className="tariff-detail-value" title={pricingTooltip}>{pricingLabel}</span>
                                            </div>
                                        )}
                                        {usesPeriods && (
                                            <span className="badge badge-neutral">
                                                {t('pages.tariffs.periodCountSummary', { count: shownPeriods.length })}
                                            </span>
                                        )}
                                        {!isShowingActive && (
                                            <span className="badge badge-warning">
                                                {t('pages.tariffs.versions.viewingOldVersion')}
                                            </span>
                                        )}
                                    </div>

                                    {series.gaps.length > 0 && (
                                        <div className="tariff-gap-warning">
                                            <FontAwesomeIcon icon={faTriangleExclamation} fixedWidth />
                                            <div>
                                                <strong>{t('pages.tariffs.versions.gapWarningTitle')}</strong>
                                                <p>
                                                    {series.gaps.map((gap) => (
                                                        `${formatShortDate(gap.start, settings)} – ${formatShortDate(gap.end, settings)}`
                                                    )).join(', ')}
                                                </p>
                                                <p className="muted">{t('pages.tariffs.versions.gapWarningBody')}</p>
                                            </div>
                                        </div>
                                    )}

                                    {isExpanded && (
                                        <>
                                            <div className="tariff-version-section">
                                                <div className="tariff-period-section-header">
                                                    <div className="tariff-period-section-title-row">
                                                        <h4>{t('pages.tariffs.versions.history')}</h4>
                                                        <span className="badge badge-neutral">{series.version_count}</span>
                                                    </div>
                                                    <div className="actions-row">
                                                        <button
                                                            className="button button-secondary button-compact"
                                                            type="button"
                                                            onClick={() => onRenameSeries(series, shown)}
                                                        >
                                                            <FontAwesomeIcon icon={faTag} fixedWidth />
                                                            {t('pages.tariffs.versions.rename')}
                                                        </button>
                                                        <button
                                                            className="button button-secondary button-compact"
                                                            type="button"
                                                            onClick={() => onDuplicate(series, shown)}
                                                        >
                                                            <FontAwesomeIcon icon={faClone} fixedWidth />
                                                            {t('pages.tariffs.versions.duplicate')}
                                                        </button>
                                                    </div>
                                                </div>

                                                <div className="tariff-version-list">
                                                    {versions.map((version) => {
                                                        const versionBadge = validityBadge(version)
                                                        const isShown = version.id === shown.id
                                                        return (
                                                            <div
                                                                key={version.id}
                                                                className={`tariff-version-row${isShown ? ' is-shown' : ''}`}
                                                            >
                                                                <button
                                                                    type="button"
                                                                    className="tariff-version-select"
                                                                    aria-pressed={isShown}
                                                                    onClick={() => setShownVersionBySeries((current) => ({
                                                                        ...current,
                                                                        [seriesKey]: version.id,
                                                                    }))}
                                                                >
                                                                    <span className={versionBadge.className}>{versionBadge.label}</span>
                                                                    <span className="tariff-version-window">
                                                                        {formatShortDate(version.valid_from, settings)} –{' '}
                                                                        {version.valid_to
                                                                            ? formatShortDate(version.valid_to, settings)
                                                                            : t('pages.tariffs.openEnded')}
                                                                    </span>
                                                                    <strong>{priceSummary(series, version)}</strong>
                                                                </button>
                                                                {/* Edit sits on the row, not only in the header:
                                                                    correcting a superseded version's end date is a
                                                                    normal follow-up to adding a new one, and going
                                                                    through "select the row, then use the header
                                                                    button" made it look unsupported. */}
                                                                <button
                                                                    className="button button-secondary button-compact"
                                                                    type="button"
                                                                    onClick={() => onEditTariff(version)}
                                                                    title={t('pages.tariffs.versions.editVersion')}
                                                                    aria-label={t('pages.tariffs.versions.editVersion')}
                                                                >
                                                                    <FontAwesomeIcon icon={faPen} fixedWidth />
                                                                </button>
                                                                <button
                                                                    className="button button-danger button-compact"
                                                                    type="button"
                                                                    disabled={deleteTariffDisabled}
                                                                    onClick={() => onDeleteTariff(version)}
                                                                    title={t('pages.tariffs.versions.deleteVersion')}
                                                                    aria-label={t('pages.tariffs.versions.deleteVersion')}
                                                                >
                                                                    <FontAwesomeIcon icon={faTrash} fixedWidth />
                                                                </button>
                                                            </div>
                                                        )
                                                    })}
                                                </div>
                                            </div>

                                            {series.version_count > 1 && (
                                                <TariffPriceHistoryChart
                                                    series={series}
                                                    allSeries={allSeries}
                                                    settings={settings}
                                                />
                                            )}

                                            {notes && (
                                                <div className="tariff-card-details">
                                                    <div className="tariff-detail-card tariff-detail-card-wide">
                                                        <span className="tariff-detail-label">{t('pages.tariffs.form.notes')}</span>
                                                        <span className="tariff-detail-value">{notes}</span>
                                                    </div>
                                                </div>
                                            )}

                                            {usesPeriods && (
                                                <div className="tariff-period-section">
                                                    <div className="tariff-period-section-header">
                                                        <div className="tariff-period-section-title-row">
                                                            <h4>{t('pages.tariffs.tariffPeriods')}</h4>
                                                            {shownPeriods.length > 0 && (
                                                                <span className="badge badge-neutral">{shownPeriods.length}</span>
                                                            )}
                                                            <span className="muted">
                                                                {formatShortDate(shown.valid_from, settings)} –{' '}
                                                                {shown.valid_to
                                                                    ? formatShortDate(shown.valid_to, settings)
                                                                    : t('pages.tariffs.openEnded')}
                                                            </span>
                                                        </div>
                                                        <button
                                                            className="button button-secondary button-compact"
                                                            type="button"
                                                            onClick={() => onOpenCreatePeriodModal(shown.id)}
                                                        >
                                                            <FontAwesomeIcon icon={faPlus} fixedWidth />
                                                            {t('pages.tariffs.addPeriod')}
                                                        </button>
                                                    </div>

                                                    {shownPeriods.length === 0 ? (
                                                        <p className="muted tariff-period-empty">{t('pages.tariffs.noPeriods')}</p>
                                                    ) : (
                                                        <div className="tariff-period-list">
                                                            {shownPeriods.map((period) => (
                                                                <div key={period.id} className="tariff-period-row">
                                                                    <div className="tariff-period-main">
                                                                        <div className="tariff-period-line">
                                                                            <span className="badge badge-neutral">
                                                                                {t(`pages.tariffs.periodTypes.${period.period_type}` as Parameters<typeof t>[0], { defaultValue: period.period_type })}
                                                                            </span>
                                                                            <strong>CHF {period.price_chf_per_kwh}/kWh</strong>
                                                                        </div>
                                                                        <div className="muted tariff-period-meta">
                                                                            {period.period_type === 'flat'
                                                                                ? `${t('pages.tariffs.allDay')} · ${t('pages.tariffs.allWeekdays')}`
                                                                                : `${period.time_from || '--'} - ${period.time_to || '--'} · ${period.weekdays || t('pages.tariffs.allWeekdays')}`}
                                                                        </div>
                                                                    </div>

                                                                    <div className="tariff-period-actions">
                                                                        <button className="button button-secondary button-compact" type="button" onClick={() => onEditPeriod(period)}>
                                                                            <FontAwesomeIcon icon={faPen} fixedWidth />
                                                                            {t('common.edit')}
                                                                        </button>
                                                                        <button
                                                                            className="button button-danger button-compact"
                                                                            type="button"
                                                                            disabled={deletePeriodDisabled}
                                                                            onClick={() => onDeletePeriod(period)}
                                                                        >
                                                                            <FontAwesomeIcon icon={faTrash} fixedWidth />
                                                                            {t('common.delete')}
                                                                        </button>
                                                                    </div>
                                                                </div>
                                                            ))}
                                                        </div>
                                                    )}
                                                </div>
                                            )}
                                        </>
                                    )}
                                </article>
                            )
                        })}
                    </div>
                </section>
            ))}
        </div>
    )
}
