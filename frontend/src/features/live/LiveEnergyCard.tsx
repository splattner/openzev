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
 * leaves `null` is never shown. Everything here is measured.
 */
export function LiveEnergyCard({ snapshot }: { snapshot: LiveSnapshot }) {
    const { t } = useTranslation()
    const titleId = useId()
    const state = liveCardState(snapshot)
    if (!state) return null
    const { own } = snapshot
    // The viewer's own figures lead (they are what a participant came for); the ZEV totals follow. A system behind the
    // meter reports its gross figures, which are what the household produces and uses; the meter alone shows only the
    // surplus and the grid draw. The split below is of the metered power, so it goes with the metered figure only.
    const ownGross = own?.gross
    const ownConsumptionW = own && state.ownConsumption ? (ownGross?.consumption_w ?? own.consumption_w) : null
    const ownProductionW = own && state.ownProduction ? (ownGross?.production_w ?? own.production_w) : null
    const split = own && state.ownSplit === 'shown' && ownGross?.consumption_w == null && own.local_w !== null && own.grid_w !== null
        ? { local: own.local_w, grid: own.grid_w }
        : null
    const ownProductionSplit = own && state.ownProductionSplit && ownGross?.production_w == null && own.production_w !== null && own.to_zev_w !== null && own.to_grid_w !== null
        ? { toZev: own.to_zev_w, toGrid: own.to_grid_w }
        : null

    // The ZEV's own figures: the production from tier `production` up, the rest only when it is exact.
    const zevProductionW = state.showProduction ? snapshot.production_w : null
    const exactFigures = state.showExact && snapshot.consumption_w !== null && snapshot.surplus_w !== null
        ? { consumption: snapshot.consumption_w, surplus: snapshot.surplus_w }
        : null
    const nothingProduced = zevProductionW !== null && kwFigure(zevProductionW) === '0.0'
    const tiles = ownConsumptionW !== null || ownProductionW !== null || zevProductionW !== null

    return (
        <section className="live-now" aria-labelledby={titleId}>
            <div className="card-header">
                <h3 id={titleId}>{t('live.title')}</h3>
                {snapshot.as_of && <span className="muted">{t('live.asOf', { time: formatClock(snapshot.as_of) })}</span>}
            </div>

            {own && !own.complete && (
                // The viewer's own tiles are withheld unless every one of their points reports; say why they are missing.
                <p>
                    <IssueText tone="warning" to="/me/metering-points">
                        {own.points_fresh === 0 ? t('live.ownQuiet') : t('live.ownPartlyQuiet', { fresh: own.points_fresh, total: own.points })}
                    </IssueText>
                </p>
            )}

            {tiles && (
                // One grid for the viewer's own figures and the ZEV's: the tiles share a row as far as the width allows.
                <div className="stat-grid">
                    {ownConsumptionW !== null && (
                        <StatCard
                            label={t('live.ownConsumptionLabel')}
                            value={kwFigure(ownConsumptionW)}
                            unit="kW"
                            hint={split ? t('live.ownSplitHint', { local: formatKw(split.local), grid: formatKw(split.grid) }) : undefined}
                        />
                    )}
                    {ownProductionW !== null && (
                        <StatCard
                            label={t('live.ownProductionLabel')}
                            value={kwFigure(ownProductionW)}
                            unit="kW"
                            hint={ownProductionSplit ? t('live.ownProductionSplitHint', { toZev: formatKw(ownProductionSplit.toZev), toGrid: formatKw(ownProductionSplit.toGrid) }) : undefined}
                        />
                    )}
                    {zevProductionW !== null && (
                        <StatCard
                            label={t('live.production')}
                            value={kwFigure(zevProductionW)}
                            unit="kW"
                            // At tier `production` the others' use is not known. Nothing produced means nothing spare, however much
                            // they use, so the tile says so and the note about their use would only confuse.
                            hint={state.tier === 'production' && nothingProduced ? t('live.nothingSpare') : undefined}
                            info={state.tier === 'production' && !nothingProduced ? t('live.othersUnknown') : undefined}
                        />
                    )}
                    {exactFigures && (
                        <>
                            <StatCard label={t('live.consumption')} value={kwFigure(exactFigures.consumption)} unit="kW" />
                            <StatCard label={t('live.spare')} value={kwFigure(exactFigures.surplus)} unit="kW" hint={t('live.spareHint')} tone="success" />
                            <StatCard
                                label={t('live.localShare')}
                                value={snapshot.local_share_pct === null ? null : formatPercentFigure(snapshot.local_share_pct)}
                                unit="%"
                                hint={t('live.localShareHint')}
                            />
                        </>
                    )}
                </div>
            )}
            {ownConsumptionW !== null && state.ownSplit === 'inconsistent' && ownGross?.consumption_w == null && <p className="muted">{t('live.ownSplitInconsistent')}</p>}

            {state.tier === 'none' && (
                ownConsumptionW !== null || ownProductionW !== null
                    ? <p className="muted">{t('live.noneZev')}</p>
                    : <p>{t('live.none')}</p>
            )}

            {state.showExact && snapshot.consumption_basis === 'connection_point' && (
                <p className="muted">{t('live.basisConnectionPoint')}</p>
            )}
        </section>
    )
}
