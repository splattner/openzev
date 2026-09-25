import { useEffect, useState } from 'react'
import { Drawer } from '@mantine/core'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import {
    faBolt,
    faClone,
    faLayerGroup,
    faPen,
    faPlus,
    faTag,
    faTrash,
    faTriangleExclamation,
    faXmark,
} from '@fortawesome/free-solid-svg-icons'
import { useTranslation } from 'react-i18next'
import { formatDateTime, formatShortDate } from '../../lib/appSettings'
import { todayLocalIso } from '../../lib/dates'
import type { AppSettings, TariffPeriod, TariffSeries, TariffVersion } from '../../types/api'
import { bandName } from './bands'
import { MONTH_KEYS, formatSeason } from './recurrence'
import { useTariffDisplay } from './useTariffDisplay'
import { TariffPriceHistoryChart } from './TariffPriceHistoryChart'
import { DynamicPriceHistoryPanel } from './DynamicPriceHistoryModal'

type TariffDetailDrawerProps = {
    /** The series to show; `null` closes the drawer. */
    series: TariffSeries | null
    /** Every series in scope — percentage tariffs derive their price from the grid ones. */
    allSeries: TariffSeries[]
    settings: AppSettings
    /** The version within `series` currently shown, defaulting to the active one. */
    shownVersionId: string | null
    onShowVersion: (versionId: string) => void
    deleteTariffDisabled: boolean
    deletePeriodDisabled: boolean
    onClose: () => void
    onEditTariff: (tariff: TariffVersion) => void
    onDeleteTariff: (tariff: TariffVersion) => void
    onOpenCreatePeriodModal: (tariffId: string) => void
    onEditPeriod: (period: TariffPeriod) => void
    onDeletePeriod: (period: TariffPeriod) => void
    onNewVersion: (series: TariffSeries, source: TariffVersion) => void
    onDuplicate: (series: TariffSeries, source: TariffVersion) => void
    onRenameSeries: (series: TariffSeries, source: TariffVersion) => void
}

/**
 * The detail view for one tariff series: version history, the price chart,
 * the dynamic source, notes and periods — everything the card list used to
 * expand in place (#728). Non-modal, like `AuditEventDrawer`: opening another
 * tariff, or picking a different version in the history list, swaps the
 * drawer's contents rather than closing and reopening it.
 */
export function TariffDetailDrawer({
    series,
    allSeries,
    settings,
    shownVersionId,
    onShowVersion,
    deleteTariffDisabled,
    deletePeriodDisabled,
    onClose,
    onEditTariff,
    onDeleteTariff,
    onOpenCreatePeriodModal,
    onEditPeriod,
    onDeletePeriod,
    onNewVersion,
    onDuplicate,
    onRenameSeries,
}: TariffDetailDrawerProps) {
    const { t } = useTranslation()
    const monthNames = MONTH_KEYS.map(
        (key) => t(`pages.tariffs.monthsShort.${key}` as Parameters<typeof t>[0]),
    )
    const today = todayLocalIso()
    const { sourceById, validityBadge, priceSummary, pricingLabelFor, pricingTooltipFor } = useTariffDisplay(settings, today)

    // Kept so the closing animation still shows the tariff that was open,
    // instead of the drawer going blank a beat before it slides away.
    const [lastSeries, setLastSeries] = useState<TariffSeries | null>(null)
    useEffect(() => {
        if (series) setLastSeries(series)
    }, [series])
    const displaySeries = series ?? lastSeries

    useEffect(() => {
        if (!series) return
        function onKeyDown(event: KeyboardEvent) {
            if (event.key === 'Escape') onClose()
        }
        document.addEventListener('keydown', onKeyDown)
        return () => document.removeEventListener('keydown', onKeyDown)
    }, [series, onClose])

    if (!displaySeries) {
        return (
            <Drawer
                opened={false}
                onClose={onClose}
                position="right"
                withCloseButton={false}
                trapFocus={false}
                lockScroll={false}
                styles={{ root: { pointerEvents: 'none' } }}
            />
        )
    }

    const versions = displaySeries.versions
    const shown = versions.find((version) => version.id === shownVersionId)
        ?? versions.find((version) => version.id === displaySeries.active_version_id)
        ?? versions[0]
    const isShowingActive = shown.id === displaySeries.active_version_id

    // Checked on the shown *version*, not the series: a series can hold both a
    // static and a dynamic version (an operator switching to dynamic pricing
    // at a version boundary, ADR 0018) since dynamic_source is deliberately
    // not one of the fields versions must agree on.
    const dynamicSource = shown.dynamic_source ? sourceById.get(shown.dynamic_source) : undefined
    const isDynamic = Boolean(shown.dynamic_source)
    // A percentage tariff is never dynamic (only billing_mode=energy can link
    // a fetched series), so its bands always apply — the single percentage
    // summary the drawer used to show is replaced by this band list (§5.7).
    const usesPeriods = (displaySeries.billing_mode === 'energy' && !isDynamic)
        || displaySeries.billing_mode === 'percentage_of_energy'
    const isPercentageTariff = displaySeries.billing_mode === 'percentage_of_energy'
    const baseRate = shown.percentage_base_summary?.price_chf_per_kwh
        ? Number(shown.percentage_base_summary.price_chf_per_kwh)
        : null
    const pricingLabel = pricingLabelFor(displaySeries, shown)
    const pricingTooltip = pricingTooltipFor(displaySeries, shown, dynamicSource)
    const notes = shown.notes?.trim()
    const badge = validityBadge(shown)

    return (
        <Drawer
            opened={Boolean(series)}
            onClose={onClose}
            position="right"
            // Wide enough to sit alongside the list rather than reading as a
            // sliver bolted onto the page — the chart and period rows want real
            // room. Capped short of the full viewport so the list stays reachable
            // for switching tariffs without closing the drawer. Sizing goes
            // through `size`, not `styles.content.width`: the drawer's own CSS
            // sets `flex: 0 0 var(--drawer-size)`, and flex-basis wins over a
            // plain `width` override.
            size="clamp(720px, 60vw, 1080px)"
            withCloseButton={false}
            trapFocus={false}
            lockScroll={false}
            styles={{
                content: { pointerEvents: 'auto', boxShadow: '-8px 0 24px -12px rgba(0, 0, 0, 0.35)' },
                inner: { padding: 0 },
                root: { pointerEvents: 'none' },
            }}
        >
            <div className="tariff-drawer">
                <header className="tariff-drawer-header">
                    <div className="tariff-drawer-heading">
                        <h3>{displaySeries.name}</h3>
                        <div className="tariff-name-badges">
                            <span className="badge badge-info">
                                {t(`pages.tariffs.billingModes.${displaySeries.billing_mode}` as Parameters<typeof t>[0], { defaultValue: displaySeries.billing_mode })}
                            </span>
                            {displaySeries.energy_type && (
                                <span className="badge badge-success">
                                    {t(`pages.tariffs.energyTypes.${displaySeries.energy_type}` as Parameters<typeof t>[0])}
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
                            {displaySeries.version_count > 1 && (
                                <span className="badge badge-neutral" title={t('pages.tariffs.versions.countTooltip')}>
                                    <FontAwesomeIcon icon={faLayerGroup} fixedWidth />{' '}
                                    {t('pages.tariffs.versions.count', { count: displaySeries.version_count })}
                                </span>
                            )}
                        </div>
                    </div>
                    <button
                        type="button"
                        className="button button-secondary"
                        onClick={onClose}
                        aria-label={t('common.close')}
                    >
                        <FontAwesomeIcon icon={faXmark} fixedWidth />
                    </button>
                </header>

                <div className="tariff-drawer-body page-stack">
                    <div className="tariff-drawer-actions actions-row actions-row-wrap">
                        <button
                            className="button button-primary button-compact"
                            type="button"
                            onClick={() => onNewVersion(displaySeries, shown)}
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
                            onClick={() => onRenameSeries(displaySeries, shown)}
                        >
                            <FontAwesomeIcon icon={faTag} fixedWidth />
                            {t('pages.tariffs.versions.rename')}
                        </button>
                        <button
                            className="button button-secondary button-compact"
                            type="button"
                            onClick={() => onDuplicate(displaySeries, shown)}
                        >
                            <FontAwesomeIcon icon={faClone} fixedWidth />
                            {t('pages.tariffs.versions.duplicate')}
                        </button>
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
                                {t('pages.tariffs.periodCountSummary', { count: shown.periods.length })}
                            </span>
                        )}
                        {!isShowingActive && (
                            <span className="badge badge-warning">
                                {t('pages.tariffs.versions.viewingOldVersion')}
                            </span>
                        )}
                    </div>

                    {displaySeries.gaps.length > 0 && (
                        <div className="tariff-gap-warning">
                            <FontAwesomeIcon icon={faTriangleExclamation} fixedWidth />
                            <div>
                                <strong>{t('pages.tariffs.versions.gapWarningTitle')}</strong>
                                <p>
                                    {displaySeries.gaps.map((gap) => (
                                        `${formatShortDate(gap.start, settings)} – ${formatShortDate(gap.end, settings)}`
                                    )).join(', ')}
                                </p>
                                <p className="muted">{t('pages.tariffs.versions.gapWarningBody')}</p>
                            </div>
                        </div>
                    )}

                    <div className="tariff-version-section">
                        <div className="tariff-period-section-header">
                            <div className="tariff-period-section-title-row">
                                <h4>{t('pages.tariffs.versions.history')}</h4>
                                <span className="badge badge-neutral">{displaySeries.version_count}</span>
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
                                            onClick={() => onShowVersion(version.id)}
                                        >
                                            <span className={versionBadge.className}>{versionBadge.label}</span>
                                            <span className="tariff-version-window">
                                                {formatShortDate(version.valid_from, settings)} –{' '}
                                                {version.valid_to
                                                    ? formatShortDate(version.valid_to, settings)
                                                    : t('pages.tariffs.openEnded')}
                                            </span>
                                            <strong>{priceSummary(displaySeries, version)}</strong>
                                        </button>
                                        {/* Edit sits on the row, not only in the actions above:
                                            correcting a superseded version's end date is a normal
                                            follow-up to adding a new one, and going through "select
                                            the row, then use the actions above" made it look
                                            unsupported. */}
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

                    {displaySeries.version_count > 1 && (
                        <TariffPriceHistoryChart
                            series={displaySeries}
                            allSeries={allSeries}
                            settings={settings}
                        />
                    )}

                    {dynamicSource && (
                        <section className="tariff-period-section">
                            <div className="tariff-period-section-header">
                                <div className="tariff-period-section-title-row">
                                    <h4>{t('pages.dynamicSources.history.sectionTitle')}</h4>
                                    <span className={dynamicSource.last_fetch_status === 'failed' ? 'badge badge-danger' : 'badge badge-info'}>
                                        {t(`pages.dynamicSources.status.${dynamicSource.last_fetch_status}` as Parameters<typeof t>[0])}
                                    </span>
                                </div>
                            </div>
                            <p className="muted tariff-period-empty">
                                {t('pages.dynamicSources.history.coverage', {
                                    from: formatDateTime(dynamicSource.covers_from, settings),
                                    to: formatDateTime(dynamicSource.covers_to, settings),
                                    count: dynamicSource.point_count,
                                })}
                            </p>
                            {/* Shown inline rather than behind a button + modal: the
                                drawer is wide enough now, and this is the one part of
                                it that used to still cost an extra click (#728). */}
                            <DynamicPriceHistoryPanel source={dynamicSource} tariff={shown} />
                        </section>
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
                                    {shown.periods.length > 0 && (
                                        <span className="badge badge-neutral">{shown.periods.length}</span>
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

                            {shown.periods.length === 0 ? (
                                <p className="muted tariff-period-empty">{t('pages.tariffs.noPeriods')}</p>
                            ) : (
                                <div className="tariff-period-list">
                                    {shown.periods.map((period) => (
                                        <div key={period.id} className="tariff-period-row">
                                            <div className="tariff-period-main">
                                                <div className="tariff-period-line">
                                                    <span className="badge badge-neutral">
                                                        {bandName(period, t(`pages.tariffs.periodTypes.${period.period_type}` as Parameters<typeof t>[0], { defaultValue: period.period_type }))}
                                                    </span>
                                                    {isPercentageTariff ? (
                                                        <span className="tariff-period-price">
                                                            <strong>{period.percentage} %</strong>
                                                            {baseRate != null && period.percentage != null && (
                                                                <span className="muted">
                                                                    {' '}
                                                                    {t('pages.tariffs.approxPrice', {
                                                                        price: (baseRate * Number(period.percentage) / 100).toFixed(3),
                                                                    })}
                                                                </span>
                                                            )}
                                                        </span>
                                                    ) : (
                                                        <strong>CHF {period.price_chf_per_kwh}/kWh</strong>
                                                    )}
                                                </div>
                                                <div className="muted tariff-period-meta">
                                                    {period.period_type === 'flat'
                                                        ? `${t('pages.tariffs.allDay')} · ${t('pages.tariffs.allWeekdays')}`
                                                        : `${period.time_from || '--'} - ${period.time_to || '--'} · ${period.weekdays || t('pages.tariffs.allWeekdays')}`}
                                                    {/* Without the season a winter price reads as the
                                                        whole year's price. */}
                                                    {formatSeason(period.months, monthNames) && ` · ${formatSeason(period.months, monthNames)}`}
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
                </div>
            </div>
        </Drawer>
    )
}
