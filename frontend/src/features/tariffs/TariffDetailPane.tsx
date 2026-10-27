import { useId, type KeyboardEvent, type ReactNode, type Ref } from 'react'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import {
    faClone,
    faEllipsisVertical,
    faPen,
    faPlus,
    faTag,
    faTrash,
    faTriangleExclamation,
    faXmark,
} from '@fortawesome/free-solid-svg-icons'
import { useTranslation } from 'react-i18next'
import { ActionMenu } from '../../components/ActionMenu'
import { formatShortDate } from '../../lib/appSettings'
import { todayBusinessIso } from '../../lib/dates'
import type { AppSettings, TariffPeriod, TariffSeries, TariffVersion } from '../../types/api'
import { bandName } from './bands'
import { MONTH_KEYS, formatSeason } from './recurrence'
import { useTariffDisplay } from './useTariffDisplay'
import { listedVersion, validityState } from './validity'
import { TariffPriceHistoryChart } from './TariffPriceHistoryChart'
import { TariffBandCoverage } from './TariffBandCoverage'
import { DynamicPriceHistoryPanel } from './DynamicPriceHistoryModal'
import { DynamicSourceSummary } from './DynamicSourceSummary'
import { TariffDisclosure } from './TariffDisclosure'
import { useAuth } from '../../lib/auth'

type TariffPaneFrameProps = {
    title: string
    /** One quiet line under the title. */
    subtitle?: ReactNode
    /** Something under the line that needs a look (a failed price fetch). */
    notice?: ReactNode
    /** X, and Escape while the pane has focus: leave the pane. */
    onClose: () => void
    /** The title is where focus lands when the pane is opened on purpose. */
    titleRef?: Ref<HTMLHeadingElement>
    children: ReactNode
}

/**
 * The pane's chrome, the same for viewing and editing: a region named by its
 * title, a close button, and the body. Not modal: no `aria-modal`, no focus
 * trap, nothing around it made inert.
 */
export function TariffPaneFrame({ title, subtitle, notice, onClose, titleRef, children }: TariffPaneFrameProps) {
    const { t } = useTranslation()
    const titleId = useId()

    function onKeyDown(event: KeyboardEvent<HTMLElement>) {
        // A menu or picker inside the pane takes the Escape that dismisses it.
        if (event.key === 'Escape' && !event.defaultPrevented) {
            event.preventDefault()
            onClose()
        }
    }

    return (
        <section className="tariff-pane" aria-labelledby={titleId} onKeyDown={onKeyDown}>
            <header className="tariff-pane-header">
                <div className="tariff-pane-heading">
                    <h2 id={titleId} ref={titleRef} tabIndex={-1}>{title}</h2>
                    {subtitle && <p className="tariff-pane-meta">{subtitle}</p>}
                    {notice}
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
            {children}
        </section>
    )
}

type TariffDetailPaneProps = {
    series: TariffSeries
    /** Every series in scope — percentage tariffs derive their price from the grid ones. */
    allSeries: TariffSeries[]
    settings: AppSettings
    /** The version within `series` currently shown, defaulting to the one in force. */
    shownVersionId: string | null
    onShowVersion: (versionId: string) => void
    deleteTariffDisabled: boolean
    deletePeriodDisabled: boolean
    onClose: () => void
    onEditTariff: (tariff: TariffVersion, actionKey: string) => void
    onDeleteTariff: (tariff: TariffVersion) => void
    onOpenCreatePeriod: (tariffId: string) => void
    onEditPeriod: (period: TariffPeriod, actionKey: string) => void
    onDeletePeriod: (period: TariffPeriod) => void
    onNewVersion: (series: TariffSeries, source: TariffVersion) => void
    onDuplicate: (series: TariffSeries, source: TariffVersion) => void
    onRenameSeries: (series: TariffSeries, source: TariffVersion) => void
    /** A viewer reads only (#761): no version, edit, rename, duplicate, delete or band changes. */
    readOnly?: boolean
    /** The title is where focus lands when the pane is opened on purpose. */
    titleRef?: Ref<HTMLHeadingElement>
    /** A form that replaces the body while the tariff is edited, with what it is for. */
    editor?: { label: string, content: ReactNode }
}

/**
 * The detail view for one tariff series, beside its list: the shown version's
 * price and validity, the dynamic source, the bands, the versions (current,
 * then scheduled, then past) and the price history. In flow, not an overlay:
 * the list keeps its space, nothing is dimmed, locked or trapped
 * (SPEC-2026-10-ui-patterns §6.2, SPEC-2026-10-tariff-split-view §5).
 */
export function TariffDetailPane({
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
    onOpenCreatePeriod,
    onEditPeriod,
    onDeletePeriod,
    onNewVersion,
    onDuplicate,
    onRenameSeries,
    readOnly = false,
    titleRef,
    editor,
}: TariffDetailPaneProps) {
    const { t } = useTranslation()
    const { user } = useAuth()
    const monthNames = MONTH_KEYS.map(
        (key) => t(`pages.tariffs.monthsShort.${key}` as Parameters<typeof t>[0]),
    )
    const today = todayBusinessIso()
    const { sourceById, priceSummary, pricingTooltipFor } = useTariffDisplay(settings, today)

    const versions = series.versions
    const shown = versions.find((version) => version.id === shownVersionId)
        ?? listedVersion(versions, today)
    const shownState = validityState(shown, today)

    // Checked on the shown *version*, not the series: a series can hold both a
    // static and a dynamic version (an operator switching to dynamic pricing
    // at a version boundary, ADR 0018) since dynamic_source is deliberately
    // not one of the fields versions must agree on.
    const dynamicSource = shown.dynamic_source ? sourceById.get(shown.dynamic_source) : undefined
    const isDynamic = Boolean(shown.dynamic_source)
    // A percentage tariff is never dynamic (only billing_mode=energy can link
    // a fetched series), so its bands always apply.
    const usesPeriods = (series.billing_mode === 'energy' && !isDynamic)
        || series.billing_mode === 'percentage_of_energy'
    const isPercentageTariff = series.billing_mode === 'percentage_of_energy'
    const baseRate = shown.percentage_base_summary?.price_chf_per_kwh
        ? Number(shown.percentage_base_summary.price_chf_per_kwh)
        : null
    const pricingLabel = priceSummary(series, shown)
    const pricingTooltip = pricingTooltipFor(series, shown, dynamicSource)
    const notes = shown.notes?.trim()
    // One quiet line of facts under the name: no status and no counts. What a
    // version's dates mean is said where they are shown.
    const meta = [
        t(`pages.tariffs.billingModes.${series.billing_mode}` as Parameters<typeof t>[0], { defaultValue: series.billing_mode }),
        series.energy_type && t(`pages.tariffs.energyTypes.${series.energy_type}` as Parameters<typeof t>[0]),
        isDynamic && t('pages.tariffs.dynamicBadge'),
    ].filter(Boolean).join(' · ')

    const dateWindow = (version: TariffVersion) => `${formatShortDate(version.valid_from, settings)} – ${
        version.valid_to ? formatShortDate(version.valid_to, settings) : t('pages.tariffs.openEnded')}`

    // Current first, then what is scheduled (nearest first; the API sends
    // newest first), then the past, folded away unless it is what is shown.
    const currentVersions = versions.filter((version) => validityState(version, today) === 'active')
    const upcomingVersions = versions.filter((version) => validityState(version, today) === 'scheduled').reverse()
    const pastVersions = versions.filter((version) => validityState(version, today) === 'expired')
    const groups = [
        { key: 'current', label: t('pages.tariffs.versions.groupCurrent'), rows: currentVersions },
        { key: 'upcoming', label: t('pages.tariffs.versions.groupUpcoming'), rows: upcomingVersions },
        { key: 'past', label: t('pages.tariffs.versions.groupPast'), rows: pastVersions },
    ].filter((group) => group.rows.length > 0)

    function versionRow(version: TariffVersion) {
        const isShown = version.id === shown.id
        const isPast = validityState(version, today) === 'expired'
        return (
            <li
                key={version.id}
                className={`tariff-version-row${isShown ? ' is-shown' : ''}${isPast ? ' is-ended' : ''}`}
            >
                <button
                    type="button"
                    className="tariff-version-select"
                    aria-pressed={isShown}
                    onClick={() => onShowVersion(version.id)}
                >
                    <span className="tariff-version-window">{dateWindow(version)}</span>
                    <strong>{priceSummary(series, version)}</strong>
                </button>
                {!readOnly && (
                    <ActionMenu
                        label={t('pages.tariffs.versions.actions')}
                        icon={<FontAwesomeIcon icon={faEllipsisVertical} fixedWidth />}
                        iconOnly
                        actionKey={`menu-${version.id}`}
                        items={[
                            { key: 'edit', label: t('pages.tariffs.versions.editVersion'), icon: <FontAwesomeIcon icon={faPen} fixedWidth />, onClick: () => onEditTariff(version, `menu-${version.id}`) },
                            { key: 'delete', label: t('pages.tariffs.versions.deleteVersion'), icon: <FontAwesomeIcon icon={faTrash} fixedWidth />, danger: true, disabled: deleteTariffDisabled, onClick: () => onDeleteTariff(version) },
                        ]}
                    />
                )}
            </li>
        )
    }

    const failedFetch = dynamicSource?.last_fetch_status === 'failed' && (
        <span
            className="badge badge-danger"
            title={t('pages.tariffs.dynamicFetchFailedTooltip', { error: dynamicSource.last_fetch_error })}
        >
            <FontAwesomeIcon icon={faTriangleExclamation} fixedWidth />{' '}
            {t('pages.tariffs.dynamicFetchFailed')}
        </span>
    )

    if (editor) {
        return (
            <TariffPaneFrame title={series.name} subtitle={editor.label} onClose={onClose} titleRef={titleRef}>
                <div className="tariff-pane-body page-stack">{editor.content}</div>
            </TariffPaneFrame>
        )
    }

    return (
        <TariffPaneFrame title={series.name} subtitle={meta} notice={failedFetch || undefined} onClose={onClose} titleRef={titleRef}>
            <div className="tariff-pane-body page-stack">
                {!readOnly && (
                    <div className="tariff-pane-actions actions-row actions-row-wrap">
                        <button
                            className="button button-primary button-compact"
                            type="button"
                            data-action-key="new-version"
                            onClick={() => onNewVersion(series, shown)}
                        >
                            <FontAwesomeIcon icon={faPlus} fixedWidth />
                            {t('pages.tariffs.versions.schedule')}
                        </button>
                        <button
                            className="button button-secondary button-compact"
                            type="button"
                            data-action-key="rename"
                            onClick={() => onRenameSeries(series, shown)}
                        >
                            <FontAwesomeIcon icon={faTag} fixedWidth />
                            {t('pages.tariffs.versions.rename')}
                        </button>
                        <button
                            className="button button-secondary button-compact"
                            type="button"
                            data-action-key="duplicate"
                            onClick={() => onDuplicate(series, shown)}
                        >
                            <FontAwesomeIcon icon={faClone} fixedWidth />
                            {t('pages.tariffs.versions.duplicate')}
                        </button>
                    </div>
                )}

                <section className="tariff-version-card" aria-label={t('pages.tariffs.versions.shown')}>
                    <div className="tariff-version-card-head">
                        <div className="tariff-version-card-title">
                            <strong className="tariff-version-card-window">{dateWindow(shown)}</strong>
                            <span className={`badge ${shownState === 'active' ? 'badge-success' : shownState === 'scheduled' ? 'badge-info' : 'badge-neutral'}`}>
                                {t(shownState === 'active'
                                    ? 'pages.tariffs.overview.current'
                                    : shownState === 'scheduled'
                                        ? 'pages.tariffs.overview.upcoming'
                                        : 'pages.tariffs.versions.statusEnded')}
                            </span>
                        </div>
                        {!readOnly && (
                            <button
                                className="button button-secondary button-compact"
                                type="button"
                                data-action-key={`edit-${shown.id}`}
                                onClick={() => onEditTariff(shown, `edit-${shown.id}`)}
                            >
                                <FontAwesomeIcon icon={faPen} fixedWidth />
                                {t('common.edit')}
                            </button>
                        )}
                    </div>
                    {!usesPeriods && (
                        <p className="tariff-version-card-price" title={pricingTooltip}>{pricingLabel}</p>
                    )}
                    {notes && <p className="tariff-version-card-notes">{notes}</p>}
                </section>

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

                {dynamicSource && (
                    <section className="tariff-period-section">
                        <div className="tariff-period-section-header">
                            <h3>{t('pages.tariffs.pane.dynamicSource')}</h3>
                        </div>
                        <DynamicSourceSummary source={dynamicSource} settings={settings} canOperate={user?.role === 'admin'} />
                        <TariffDisclosure summary={t('pages.dynamicSources.history.sectionTitle')}>
                            <DynamicPriceHistoryPanel source={dynamicSource} tariff={shown} />
                        </TariffDisclosure>
                    </section>
                )}

                {usesPeriods && (
                    <section className="tariff-period-section">
                        <div className="tariff-period-section-header">
                            <h3>{t('pages.tariffs.tariffPeriods')}</h3>
                            {!readOnly && (
                                <button
                                    className="button button-secondary button-compact"
                                    type="button"
                                    data-action-key="add-period"
                                    onClick={() => onOpenCreatePeriod(shown.id)}
                                >
                                    <FontAwesomeIcon icon={faPlus} fixedWidth />
                                    {t('pages.tariffs.addPeriod')}
                                </button>
                            )}
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

                                        {!readOnly && (
                                            <div className="tariff-period-actions">
                                                <button
                                                    className="button button-secondary button-compact"
                                                    type="button"
                                                    data-action-key={`edit-period-${period.id}`}
                                                    onClick={() => onEditPeriod(period, `edit-period-${period.id}`)}
                                                    title={t('common.edit')}
                                                    aria-label={t('common.edit')}
                                                >
                                                    <FontAwesomeIcon icon={faPen} fixedWidth />
                                                </button>
                                                <button
                                                    className="button button-danger button-compact"
                                                    type="button"
                                                    disabled={deletePeriodDisabled}
                                                    onClick={() => onDeletePeriod(period)}
                                                    title={t('common.delete')}
                                                    aria-label={t('common.delete')}
                                                >
                                                    <FontAwesomeIcon icon={faTrash} fixedWidth />
                                                </button>
                                            </div>
                                        )}
                                    </div>
                                ))}
                            </div>
                        )}
                        <TariffBandCoverage bands={shown.periods} validity={shown} />
                    </section>
                )}

                {versions.length > 1 && <section className="tariff-version-section">
                    <h3>{t('pages.tariffs.versions.history')}</h3>
                    {groups.map((group) => {
                        const list = <ul className="tariff-version-list">{group.rows.map(versionRow)}</ul>
                        // Several groups need their names; one group is just the list.
                        return (
                            <div key={group.key} className="tariff-version-group">
                                {groups.length > 1 && group.key !== 'past' && (
                                    <h4 className="tariff-detail-label">{group.label}</h4>
                                )}
                                {group.key === 'past' ? (
                                    <TariffDisclosure
                                        summary={group.label}
                                        defaultOpen={shownState === 'expired' || groups.length === 1}
                                    >
                                        {list}
                                    </TariffDisclosure>
                                ) : list}
                            </div>
                        )
                    })}
                </section>}

                {series.version_count > 1 && (
                    <TariffDisclosure summary={t('pages.tariffs.priceHistory.title')}>
                        <TariffPriceHistoryChart
                            series={series}
                            allSeries={allSeries}
                            settings={settings}
                            titled={false}
                        />
                    </TariffDisclosure>
                )}
            </div>
        </TariffPaneFrame>
    )
}
