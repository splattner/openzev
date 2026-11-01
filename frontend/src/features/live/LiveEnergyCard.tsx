import { useId } from 'react'
import { useTranslation } from 'react-i18next'
import { formatClock, formatKw, kwFigure, liveCardState } from '../../lib/live'
import { formatPercentFigure } from '../../lib/numbers'
import type { LiveSnapshot } from '../../types/api'
import { IssueText } from '../../components/IssueText'
import { StatCard } from '../../components/StatCard'

/**
 * What the ZEV produces and uses right now (SPEC-2026-live-energy-data §7.1). The tier decides what
 * may be said: below `exact` there is no spare power, local share or split, and a value the payload
 * leaves `null` is never shown. Everything here is measured and labelled live, indicative.
 */
export function LiveEnergyCard({ snapshot }: { snapshot: LiveSnapshot }) {
    const { t } = useTranslation()
    const titleId = useId()
    const state = liveCardState(snapshot)
    if (!state) return null
    const { own, coverage } = snapshot
    const connectionState = coverage.connection_point
    // The viewer's own figures lead (they are what a participant came for); the ZEV totals follow.
    const ownConsumptionW = own && state.ownConsumption ? own.consumption_w : null
    const split = own && state.ownSplit === 'shown' && own.local_w !== null && own.grid_w !== null ? { local: own.local_w, grid: own.grid_w } : null
    const ownProduction = own && state.ownProductionSplit && own.production_w !== null && own.to_zev_w !== null && own.to_grid_w !== null
        ? { total: own.production_w, toZev: own.to_zev_w, toGrid: own.to_grid_w }
        : null

    return (
        <section className="card" aria-labelledby={titleId}>
            <div className="card-header">
                <h3 id={titleId}>
                    {t('live.title')}
                    <span className="badge badge-info">{t('live.badge')}</span>
                </h3>
                {snapshot.as_of && <span className="muted">{t('live.asOf', { time: formatClock(snapshot.as_of) })}</span>}
            </div>

            {own && !own.complete && (
                // The viewer's own tiles are withheld unless every one of their points reports; say why they are missing.
                <p>
                    <IssueText tone="warning" to="/me/metering-points">
                        {t(own.points_fresh === 0 ? 'live.ownQuiet' : 'live.ownPartlyQuiet')}
                    </IssueText>
                </p>
            )}

            {(ownConsumptionW !== null || ownProduction) && (
                <div className="stat-grid">
                    {ownConsumptionW !== null && (
                        <StatCard
                            label={t('live.ownConsumptionLabel')}
                            value={kwFigure(ownConsumptionW)}
                            unit="kW"
                            hint={split ? t('live.ownSplitHint', { local: formatKw(split.local), grid: formatKw(split.grid) }) : undefined}
                        />
                    )}
                    {ownProduction && (
                        <StatCard
                            label={t('live.ownProductionLabel')}
                            value={kwFigure(ownProduction.total)}
                            unit="kW"
                            hint={t('live.ownProductionSplitHint', { toZev: formatKw(ownProduction.toZev), toGrid: formatKw(ownProduction.toGrid) })}
                        />
                    )}
                </div>
            )}
            {ownConsumptionW !== null && state.ownSplit === 'inconsistent' && <p className="muted">{t('live.ownSplitInconsistent')}</p>}

            {state.tier === 'none' && (
                <p>{t('live.none')}</p>
            )}

            {state.tier === 'production' && state.showProduction && snapshot.production_w !== null && (
                <>
                    <p>
                        <strong>{t('live.zevProduces', { value: formatKw(snapshot.production_w) })}</strong>
                    </p>
                    <p className="muted">{t('live.othersUnknown')}</p>
                </>
            )}

            {state.showExact && snapshot.production_w !== null && snapshot.consumption_w !== null && snapshot.surplus_w !== null && (
                <div className="stat-grid">
                    <StatCard label={t('live.production')} value={kwFigure(snapshot.production_w)} unit="kW" />
                    <StatCard label={t('live.consumption')} value={kwFigure(snapshot.consumption_w)} unit="kW" />
                    <StatCard label={t('live.spare')} value={kwFigure(snapshot.surplus_w)} unit="kW" hint={t('live.spareHint')} tone="success" />
                    <StatCard
                        label={t('live.localShare')}
                        value={snapshot.local_share_pct === null ? null : formatPercentFigure(snapshot.local_share_pct)}
                        unit="%"
                        hint={t('live.localShareHint')}
                    />
                </div>
            )}
            {state.showExact && snapshot.consumption_basis === 'connection_point' && (
                <p className="muted">{t('live.basisConnectionPoint')}</p>
            )}

            <p className="muted">
                {t('live.coverage', state.reporting)}
                {connectionState && ` · ${t('live.connectionPoint', { state: t(`live.state.${connectionState}`) })}`}
            </p>
        </section>
    )
}
