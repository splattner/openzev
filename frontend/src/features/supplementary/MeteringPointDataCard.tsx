import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../../lib/auth'
import { forecastEligible, historyEligible, liveEligible, sourceFor } from '../../lib/supplementary'
import type { EligibleMeteringPoint, SupplementarySource } from '../../types/api'
import { CapabilityRows } from './CapabilityRows'
import { ForecastConnectDialog } from './ForecastConnectDialog'
import { MeteringDataLink } from './MeteringDataLink'
import { SupplementarySourceModal, type ConnectCapability } from './SupplementarySourceModal'

interface Props {
    point: EligibleMeteringPoint
    /** What the meter is (its location or name), under the meter id. */
    description?: string
    /** The signed-in user's visible sources; `undefined` while they load or after they failed. */
    sources: SupplementarySource[] | undefined
    /** The source list is still loading or failed: a source the point is known to have cannot be shown yet. */
    sourcesUnavailable?: 'loading' | 'error'
    onRetrySources?: () => void
    /** Open a source's details: the host shows them beside the cards (SPEC-2026-10-ui-patterns rule A). */
    onOpenSource: (source: SupplementarySource) => void
    /** The source whose details are open, to mark its card and button. */
    selectedSourceId?: string | null
    /** A source was just connected from this card; the host opens it. */
    onConnected?: (source: SupplementarySource) => void
}

/**
 * The energy data of one metering point the participant holds, in one card: a row per capability the
 * point can have (history, live) with the source that provides it, a Connect on each row that has none and,
 * while several are missing, one primary that starts them together. Everything about a
 * source is in its pane, which the page owns. The figures are only shown (live) or used for statistics (history), never
 * for billing.
 */
export function MeteringPointDataCard({ point, description, sources, sourcesUnavailable, onRetrySources, onOpenSource, selectedSourceId, onConnected }: Props) {
    const { t } = useTranslation()
    const { isImpersonating } = useAuth()
    const [connecting, setConnecting] = useState<ConnectCapability[] | null>(null)

    const eligible = { history: historyEligible(point), live: liveEligible(point), forecast: forecastEligible(point) }
    const capabilities = (['history', 'live', 'forecast'] as const).filter((capability) => eligible[capability])
    const unconnected = capabilities.filter((capability) => !sourceFor(sources, point.metering_point, capability))
    // Forecast is connected on its own (forecast.solar needs no credentials); the others share one flow.
    const connectable = unconnected.filter((capability): capability is ConnectCapability => capability !== 'forecast')
    const [connectingForecast, setConnectingForecast] = useState(false)
    const historySource = sourceFor(sources, point.metering_point, 'history')
    // A Solar Manager key the vendor refused is the whole source's problem, history or live only.
    const reconnectSource = [historySource, sourceFor(sources, point.metering_point, 'live'), sourceFor(sources, point.metering_point, 'forecast')].find((source) => source?.status === 'reconnect_required')
    const knowsSource = !!(point.source || point.sources?.history || point.sources?.live || point.sources?.forecast)
    // Eligibility says a source exists but its details are not here yet: offering Connect would be wrong.
    const unavailable = knowsSource && !sources ? sourcesUnavailable : undefined
    const selected = !!selectedSourceId && !!sources?.some((source) => source.id === selectedSourceId && source.metering_point === point.metering_point)

    return (
        <>
            <article className="card" style={{ display: 'grid', gap: '1rem', gridTemplateColumns: 'minmax(0, 1fr)' }} aria-label={point.meter_id} data-selected={selected || undefined}>
                <header className="card-header-row">
                    <div className="card-title-block">
                        <h3>{point.meter_id}</h3>
                        {/* A classification is quiet text, not a pill (UI patterns §10.1). */}
                        <small className="muted">{[description, eligible.history ? t('behindMeter.badge') : null].filter(Boolean).join(' · ')}</small>
                    </div>
                    <MeteringDataLink meteringPointId={point.metering_point} />
                </header>

                {reconnectSource && (
                    <div className="warning-banner" role="alert">
                        <strong>{t('supplementary.reconnect.title')}</strong>
                        <p style={{ margin: '0.25rem 0 0' }}>{reconnectSource.last_error || t('supplementary.reconnect.body')}</p>
                    </div>
                )}
                {historySource?.status === 'error' && historySource.last_error && (
                    <div className="warning-banner" role="status">
                        <p className="m-0">{historySource.last_error}</p>
                    </div>
                )}

                {unavailable === 'loading' && <p className="muted m-0">{t('common.loading')}</p>}
                {unavailable === 'error' && (
                    <div className="error-banner" role="alert">
                        {t('supplementary.section.loadError')}
                        {onRetrySources && (
                            <button type="button" className="button button-secondary button-compact" onClick={onRetrySources} style={{ marginLeft: '0.75rem' }}>
                                {t('common.retry')}
                            </button>
                        )}
                    </div>
                )}
                {!unavailable && (
                    <>
                        <CapabilityRows
                            meteringPointId={point.metering_point}
                            capabilities={capabilities}
                            sources={sources}
                            onOpenSource={onOpenSource}
                            selectedSourceId={selectedSourceId}
                            onConnect={(capability) => (capability === 'forecast' ? setConnectingForecast(true) : setConnecting([capability]))}
                        />
                        {/* One missing capability is connected from its own row; the primary is for starting several at once. */}
                        {connectable.length > 1 && (
                            <div className="actions-row actions-row-wrap">
                                <button
                                    type="button"
                                    className="button button-primary"
                                    disabled={isImpersonating}
                                    title={isImpersonating ? t('account.impersonationRestrictions') : undefined}
                                    onClick={() => setConnecting(connectable)}
                                >
                                    {t('supplementary.card.connect')}
                                </button>
                            </div>
                        )}
                    </>
                )}
            </article>
            {connecting && (
                <SupplementarySourceModal
                    point={point}
                    available={connectable}
                    initial={connecting}
                    sources={sources}
                    onConnected={onConnected}
                    onClose={() => setConnecting(null)}
                />
            )}
            {connectingForecast && <ForecastConnectDialog holder="participant" point={point} sources={sources} onClose={() => setConnectingForecast(false)} />}
        </>
    )
}
