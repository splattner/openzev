import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import {
    faBolt,
    faChevronRight,
    faLayerGroup,
    faPen,
    faTriangleExclamation,
} from '@fortawesome/free-solid-svg-icons'
import { useTranslation } from 'react-i18next'
import { todayLocalIso } from '../../lib/dates'
import type { AppSettings, Tariff, TariffSeries } from '../../types/api'
import { seriesKeyOf, useTariffDisplay } from './useTariffDisplay'

type TariffSeriesSection = {
    category: Tariff['category']
    series: TariffSeries[]
}

type TariffCategorySectionsProps = {
    tariffSections: TariffSeriesSection[]
    settings: AppSettings
    /** The series currently shown in the detail drawer, so its card can be highlighted. */
    openSeriesKey: string | null
    onEditTariff: (tariff: Tariff) => void
    onOpenDetail: (series: TariffSeries) => void
}

/**
 * The tariff list: one compact card per series. Everything beyond "what does
 * this cost right now" — version history, the price chart, periods, notes —
 * lives in `TariffDetailDrawer` instead of expanding in place, so browsing
 * the list no longer means the page growing and shrinking under you (#728).
 */
export function TariffCategorySections({
    tariffSections,
    settings,
    openSeriesKey,
    onEditTariff,
    onOpenDetail,
}: TariffCategorySectionsProps) {
    const { t } = useTranslation()
    const today = todayLocalIso()
    const { sourceById, validityBadge, pricingLabelFor, pricingTooltipFor } = useTariffDisplay(settings, today)

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
                            const seriesKey = seriesKeyOf(series)
                            const versions = series.versions
                            const active = versions.find((version) => version.id === series.active_version_id)
                                ?? versions[0]

                            const dynamicSource = active.dynamic_source ? sourceById.get(active.dynamic_source) : undefined
                            const isDynamic = Boolean(active.dynamic_source)
                            const usesPeriods = series.billing_mode === 'energy' && !isDynamic
                            const pricingLabel = pricingLabelFor(series, active)
                            const pricingTooltip = pricingTooltipFor(series, active, dynamicSource)
                            const badge = validityBadge(active)
                            const isOpen = seriesKey === openSeriesKey

                            return (
                                <article
                                    key={seriesKey}
                                    className={`tariff-card${isOpen ? ' is-open' : ''}`}
                                >
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
                                                    {isDynamic && (
                                                        <span
                                                            className={
                                                                dynamicSource?.last_fetch_status === 'failed'
                                                                    ? 'badge badge-danger'
                                                                    : 'badge badge-info'
                                                            }
                                                            title={dynamicSource?.last_fetch_status === 'failed'
                                                                ? t('pages.tariffs.dynamicFetchFailedTooltip', { error: dynamicSource.last_fetch_error })
                                                                : t('pages.tariffs.dynamicBadgeTooltip')}
                                                        >
                                                            <FontAwesomeIcon icon={faBolt} fixedWidth />{' '}
                                                            {t('pages.tariffs.dynamicBadge')}
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
                                            <button className="button button-secondary button-compact" type="button" onClick={() => onEditTariff(active)}>
                                                <FontAwesomeIcon icon={faPen} fixedWidth />
                                                {t('common.edit')}
                                            </button>
                                            <button
                                                className="button button-primary button-compact"
                                                type="button"
                                                aria-expanded={isOpen}
                                                onClick={() => onOpenDetail(series)}
                                            >
                                                {t('pages.tariffs.viewDetails')}
                                                <FontAwesomeIcon icon={faChevronRight} fixedWidth />
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
                                                {t('pages.tariffs.periodCountSummary', { count: active.periods.length })}
                                            </span>
                                        )}
                                    </div>
                                </article>
                            )
                        })}
                    </div>
                </section>
            ))}
        </div>
    )
}
