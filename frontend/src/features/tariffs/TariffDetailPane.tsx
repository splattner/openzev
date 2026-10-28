import { useState, type ReactNode, type Ref } from 'react'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import {
    faChevronDown,
    faClone,
    faPen,
    faPlus,
    faTag,
    faTriangleExclamation,
} from '@fortawesome/free-solid-svg-icons'
import { useTranslation } from 'react-i18next'
import { formatShortDate } from '../../lib/appSettings'
import { todayBusinessIso } from '../../lib/dates'
import type { AppSettings, TariffPeriod, TariffSeries, TariffVersion } from '../../types/api'
import { bandName } from './bands'
import { MONTH_KEYS, formatSeason } from './recurrence'
import { useTariffDisplay } from './useTariffDisplay'
import { listedVersion, validityState } from './validity'
import { deltaSummary, formatDelta, versionDeltas, type PriceDelta } from './priceDelta'
import { bandCoverage } from './bandCoverage'
import { TariffPriceHistoryChart } from './TariffPriceHistoryChart'
import { TariffBandCoverage } from './TariffBandCoverage'
import { DynamicPriceHistoryPanel } from './DynamicPriceHistoryModal'
import { DynamicSourceSummary } from './DynamicSourceSummary'
import { DetailPane } from '../../components/DetailPane'
import { Disclosure } from '../../components/Disclosure'
import { IssueText } from '../../components/IssueText'
import { useAuth } from '../../lib/auth'

type TariffDetailPaneProps = {
    series: TariffSeries
    /** Every series in scope — percentage tariffs derive their price from the grid ones. */
    allSeries: TariffSeries[]
    settings: AppSettings
    /** The version within `series` currently shown, defaulting to the one in force. */
    shownVersionId: string | null
    onShowVersion: (versionId: string) => void
    onClose: () => void
    onEditTariff: (tariff: TariffVersion, actionKey: string) => void
    onOpenCreatePeriod: (tariffId: string) => void
    onEditPeriod: (period: TariffPeriod, actionKey: string) => void
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
    onClose,
    onEditTariff,
    onOpenCreatePeriod,
    onEditPeriod,
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
    // A scheduled version starts folded to a line; what a person opened or folded stays so.
    const [unfolded, setUnfolded] = useState<Record<string, boolean>>({})
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
    const isPercentageTariff = series.billing_mode === 'percentage_of_energy'
    // One quiet line of facts under the name: no status and no counts. What a
    // version's dates mean is said where they are shown.
    const meta = [
        t(`pages.tariffs.billingModes.${series.billing_mode}` as Parameters<typeof t>[0], { defaultValue: series.billing_mode }),
        series.energy_type && t(`pages.tariffs.energyTypes.${series.energy_type}` as Parameters<typeof t>[0]),
        isDynamic && t('pages.tariffs.dynamicBadge'),
    ].filter(Boolean).join(' · ')

    const dateWindow = (version: TariffVersion) => `${formatShortDate(version.valid_from, settings)} – ${
        version.valid_to ? formatShortDate(version.valid_to, settings) : t('pages.tariffs.openEnded')}`

    // In time order: what is in force, then what is scheduled (nearest first;
    // the API sends newest first), with the past folded into the history.
    const currentVersions = versions.filter((version) => validityState(version, today) === 'active')
    const upcomingVersions = versions.filter((version) => validityState(version, today) === 'scheduled').reverse()
    const pastVersions = versions.filter((version) => validityState(version, today) === 'expired')
    const rowNotes = listedVersion(versions, today).notes?.trim()
    const inForceAndNext = [...currentVersions, ...upcomingVersions]

    /** The version a scheduled one replaces, to read its prices against. */
    function previousOf(version: TariffVersion) {
        const index = inForceAndNext.indexOf(version)
        return index < 1 || validityState(version, today) !== 'scheduled' ? null : inForceAndNext[index - 1]
    }
    function deltasFor(version: TariffVersion) {
        const previous = previousOf(version)
        return previous ? versionDeltas(series, previous, version) : null
    }

    function change(value: PriceDelta) {
        return (
            <span className="tariff-change">
                <span className="visually-hidden">{t('pages.tariffs.change.label')} </span>
                {formatDelta(value, (diff) => t('pages.tariffs.change.points', { diff }))}
            </span>
        )
    }

    function versionRow(version: TariffVersion) {
        const isShown = version.id === shown.id
        return (
            <li key={version.id} className={`tariff-version-row is-ended${isShown ? ' is-shown' : ''}`}>
                <button
                    type="button"
                    className="tariff-version-select"
                    aria-pressed={isShown}
                    onClick={() => onShowVersion(version.id)}
                >
                    <span className="tariff-version-window">{dateWindow(version)}</span>
                    <strong>{priceSummary(series, version)}</strong>
                </button>
            </li>
        )
    }

    /** One version in full: its window and standing, its price or bands, what it changes. */
    function versionCard(version: TariffVersion) {
        const state = validityState(version, today)
        const source = version.dynamic_source ? sourceById.get(version.dynamic_source) : undefined
        // A version with a fetched price has no bands of its own (see above).
        const hasBands = (series.billing_mode === 'energy' && !version.dynamic_source) || isPercentageTariff
        const deltas = deltasFor(version)
        const base = version.percentage_base_summary?.price_chf_per_kwh
            ? Number(version.percentage_base_summary.price_chf_per_kwh)
            : null
        // The overview row already shows its own version's notes.
        const versionNotes = version.notes?.trim() !== rowNotes ? version.notes?.trim() : undefined
        // The version in force is always open; a scheduled one is a line until asked for.
        const collapsible = state === 'scheduled'
        const open = !collapsible || (unfolded[version.id] ?? version.id === shown.id)
        const bodyId = `tariff-version-${version.id}`
        const previous = previousOf(version)
        const comparison = previous ? deltaSummary(series, previous, version, (diff) => t('pages.tariffs.change.points', { diff })) : null
        const uncovered = hasBands && version.periods.length > 0 && bandCoverage(version.periods, version).uncovered
        const status = (
            <span className={`badge ${state === 'active' ? 'badge-success' : state === 'scheduled' ? 'badge-info' : 'badge-neutral'}`}>
                {t(state === 'active'
                    ? 'pages.tariffs.overview.current'
                    : state === 'scheduled'
                        ? 'pages.tariffs.overview.upcoming'
                        : 'pages.tariffs.versions.statusEnded')}
            </span>
        )
        return (
            <section
                key={version.id}
                className={`tariff-version-card${version.id === shown.id && inForceAndNext.length > 1 ? ' is-shown' : ''}`}
                aria-label={dateWindow(version)}
            >
                <div className="tariff-version-card-head">
                    {collapsible ? (
                        <button
                            type="button"
                            className="tariff-version-toggle disclosure-toggle"
                            aria-expanded={open}
                            aria-controls={bodyId}
                            onClick={() => setUnfolded((current) => ({ ...current, [version.id]: !open }))}
                        >
                            <FontAwesomeIcon icon={faChevronDown} className="disclosure-toggle-icon" fixedWidth aria-hidden="true" />
                            {status}
                            <span className="tariff-version-card-window">{dateWindow(version)}</span>
                        </button>
                    ) : (
                        <div className="tariff-version-card-title">
                            {status}
                            <span className="tariff-version-card-window">{dateWindow(version)}</span>
                        </div>
                    )}
                    {!readOnly && (
                        <button
                            className="button button-secondary button-compact"
                            type="button"
                            data-action-key={`edit-${version.id}`}
                            onClick={() => onEditTariff(version, `edit-${version.id}`)}
                        >
                            <FontAwesomeIcon icon={faPen} fixedWidth />
                            {t('common.edit')}
                        </button>
                    )}
                </div>
                {!open && (
                    <p className="tariff-version-card-summary">
                        <span>{priceSummary(series, version)}</span>
                        {comparison && <span className="tariff-change">({comparison})</span>}
                        {uncovered && (
                            <IssueText title={t('pages.tariffs.coverage.badgeTooltip')}>
                                {t('pages.tariffs.coverage.badge')}
                            </IssueText>
                        )}
                    </p>
                )}
                {open && <div id={bodyId} className="tariff-version-card-body">
                {!hasBands && (
                    <p className="tariff-version-card-price" title={pricingTooltipFor(series, version, source)}>
                        {priceSummary(series, version)}
                        {deltas?.version && <> {change(deltas.version)}</>}
                    </p>
                )}
                {versionNotes && <p className="tariff-version-card-notes">{versionNotes}</p>}

                {source && (
                    <section className="tariff-period-section">
                        <div className="tariff-period-section-header">
                            <h4>{t('pages.tariffs.pane.dynamicSource')}</h4>
                        </div>
                        <DynamicSourceSummary source={source} settings={settings} canOperate={user?.role === 'admin'} />
                        <Disclosure lazy summary={t('pages.dynamicSources.history.sectionTitle')}>
                            <DynamicPriceHistoryPanel source={source} tariff={version} />
                        </Disclosure>
                    </section>
                )}

                {hasBands && (
                    <section className="tariff-period-section">
                        <div className="tariff-period-section-header">
                            <h4>{t('pages.tariffs.tariffPeriods')}</h4>
                        </div>

                        {version.periods.length === 0 ? (
                            <p className="muted tariff-period-empty">{t('pages.tariffs.noPeriods')}</p>
                        ) : (
                            <div className="tariff-period-list">
                                {version.periods.map((period) => {
                                    const periodChange = deltas?.bands.get(period.id)
                                    return (
                                        <div key={period.id} className="tariff-period-row">
                                            <div className="tariff-period-main">
                                                <div className="tariff-period-line">
                                                    <span className="badge badge-neutral">
                                                        {bandName(period, t(`pages.tariffs.periodTypes.${period.period_type}` as Parameters<typeof t>[0], { defaultValue: period.period_type }))}
                                                    </span>
                                                    {isPercentageTariff ? (
                                                        <span className="tariff-period-price">
                                                            <strong>{period.percentage} %</strong>
                                                            {base != null && period.percentage != null && (
                                                                <span className="muted">
                                                                    {' '}
                                                                    {t('pages.tariffs.approxPrice', {
                                                                        price: (base * Number(period.percentage) / 100).toFixed(3),
                                                                    })}
                                                                </span>
                                                            )}
                                                        </span>
                                                    ) : (
                                                        <strong>CHF {period.price_chf_per_kwh}/kWh</strong>
                                                    )}
                                                    {periodChange && change(periodChange)}
                                                </div>
                                                <div className="muted tariff-period-meta">
                                                    {period.period_type === 'flat'
                                                        ? `${t('pages.tariffs.allDay')} · ${t('pages.tariffs.allWeekdays')}`
                                                        : `${period.time_from && period.time_to ? `${period.time_from} - ${period.time_to}` : t('pages.tariffs.rateCard.allOtherHours')} · ${period.weekdays || t('pages.tariffs.allWeekdays')}`}
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
                                                </div>
                                            )}
                                        </div>
                                    )
                                })}
                            </div>
                        )}
                        {!readOnly && (
                            <button
                                className="button button-ghost button-compact tariff-add-band"
                                type="button"
                                data-action-key={`add-period-${version.id}`}
                                onClick={() => onOpenCreatePeriod(version.id)}
                            >
                                <FontAwesomeIcon icon={faPlus} fixedWidth />
                                {t('pages.tariffs.addPeriod')}
                            </button>
                        )}
                        <TariffBandCoverage bands={version.periods} validity={version} />
                    </section>
                )}
                </div>}
            </section>
        )
    }

    const failedFetch = dynamicSource?.last_fetch_status === 'failed' && (
        <IssueText title={t('pages.tariffs.dynamicFetchFailedTooltip', { error: dynamicSource.last_fetch_error })}>
            {t('pages.tariffs.dynamicFetchFailed')}
        </IssueText>
    )

    if (editor) {
        return (
            <DetailPane title={series.name} subtitle={editor.label} onClose={onClose} titleRef={titleRef}>
                <div className="detail-pane-body page-stack">{editor.content}</div>
            </DetailPane>
        )
    }

    return (
        <DetailPane title={series.name} subtitle={meta} notice={failedFetch || undefined} onClose={onClose} titleRef={titleRef}>
            <div className="detail-pane-body page-stack">
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

                {inForceAndNext.map(versionCard)}

                {pastVersions.length > 0 && (
                    <Disclosure
                        lazy
                        key={`${series.name}-${shownState === 'expired'}`}
                        summary={t('pages.tariffs.versions.history')}
                        defaultOpen={shownState === 'expired' || inForceAndNext.length === 0}
                    >
                        <div className="page-stack">
                            {series.version_count > 1 && (
                                <TariffPriceHistoryChart
                                    series={series}
                                    allSeries={allSeries}
                                    settings={settings}
                                    titled={false}
                                />
                            )}
                            <ul className="tariff-version-list">{pastVersions.map(versionRow)}</ul>
                            {shownState === 'expired' && versionCard(shown)}
                        </div>
                    </Disclosure>
                )}
            </div>
        </DetailPane>
    )
}
