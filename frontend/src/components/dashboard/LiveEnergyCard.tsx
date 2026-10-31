import { useId } from 'react'
import { useTranslation } from 'react-i18next'
import { formatClock, formatKw, kwFigure, liveCardState } from '../../lib/live'
import { formatPercentFigure } from '../../lib/numbers'
import type { LiveSnapshot } from '../../types/api'
import { StatCard } from '../StatCard'

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

    return (
        <section className="card" aria-labelledby={titleId}>
            <div className="card-header">
                <h3 id={titleId}>
                    {t('live.title')}
                    <span className="badge badge-info">{t('live.badge')}</span>
                </h3>
                {snapshot.as_of && <span className="muted">{t('live.asOf', { time: formatClock(snapshot.as_of) })}</span>}
            </div>

            {state.tier === 'none' && (
                <>
                    <p>{t('live.none')}</p>
                    {state.detailed && (
                        <p className="muted">
                            {t('live.noneReason', { fresh: coverage.producing_fresh, total: coverage.producing_points })}
                        </p>
                    )}
                </>
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

            {own && state.ownConsumption && own.consumption_w !== null && (
                <>
                    {state.ownSplit === 'shown' && own.local_w !== null && own.grid_w !== null ? (
                        <p>{t('live.ownSplit', { total: formatKw(own.consumption_w), local: formatKw(own.local_w), grid: formatKw(own.grid_w) })}</p>
                    ) : (
                        <p>{t('live.ownConsumption', { value: formatKw(own.consumption_w) })}</p>
                    )}
                    {state.ownSplit === 'inconsistent' && <p className="muted">{t('live.ownSplitInconsistent')}</p>}
                </>
            )}
            {own && state.ownProductionSplit && own.production_w !== null && own.to_zev_w !== null && own.to_grid_w !== null && (
                <p>
                    {t('live.ownProductionSplit', {
                        total: formatKw(own.production_w),
                        toZev: formatKw(own.to_zev_w),
                        toGrid: formatKw(own.to_grid_w),
                    })}
                </p>
            )}

            <p className="muted">
                {t('live.coverage', { fresh: coverage.consuming_fresh, total: coverage.consuming_points })}
                {connectionState && ` · ${t('live.connectionPoint', { state: t(`live.state.${connectionState}`) })}`}
            </p>
        </section>
    )
}
