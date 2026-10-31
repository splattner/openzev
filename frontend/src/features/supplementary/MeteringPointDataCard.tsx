import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { BehindMeterBadge } from '../../components/BehindMeterBadge'
import { useAuth } from '../../lib/auth'
import { historyEligible, liveEligible, sourceFor } from '../../lib/supplementary'
import type { EligibleMeteringPoint, SupplementarySource } from '../../types/api'
import { CapabilityRows, type RowCapability } from './CapabilityRows'
import { MeteringDataLink } from './MeteringDataLink'
import { SourceDialog, type ConfirmOptions } from './SourceDialog'
import { SupplementarySourceModal } from './SupplementarySourceModal'

interface Props {
    point: EligibleMeteringPoint
    /** The signed-in user's visible sources; `undefined` while they load or after they failed. */
    sources: SupplementarySource[] | undefined
    /** The source list is still loading or failed: a source the point is known to have cannot be shown yet. */
    sourcesUnavailable?: 'loading' | 'error'
    onRetrySources?: () => void
    confirm: (options: ConfirmOptions) => void
}

/**
 * The energy data of one metering point the participant holds, in one card: a row per capability the
 * point can have (history, live) with the source that provides it, and one Connect. Everything about a
 * source is in its dialog. The figures are only shown (live) or used for statistics (history), never
 * for billing.
 */
export function MeteringPointDataCard({ point, sources, sourcesUnavailable, onRetrySources, confirm }: Props) {
    const { t } = useTranslation()
    const { isImpersonating } = useAuth()
    const [connecting, setConnecting] = useState<RowCapability[] | null>(null)
    // The dialogs are rendered next to the card and decided by their own state, never by what the source
    // list says: creating a source changes the rows while a push source's one-time token is on screen.
    const [openSourceId, setOpenSourceId] = useState<string | null>(null)

    const eligible = { history: historyEligible(point), live: liveEligible(point) }
    const capabilities = (['history', 'live'] as const).filter((capability) => eligible[capability])
    const unconnected = capabilities.filter((capability) => !sourceFor(sources, point.metering_point, capability))
    const historySource = sourceFor(sources, point.metering_point, 'history')
    const knowsSource = !!(point.source || point.sources?.history || point.sources?.live)
    // Eligibility says a source exists but its details are not here yet: offering Connect would be wrong.
    const unavailable = knowsSource && !sources ? sourcesUnavailable : undefined
    const openSource = sources?.find((source) => source.id === openSourceId)

    return (
        <>
            <article className="card" style={{ display: 'grid', gap: '1rem', gridTemplateColumns: 'minmax(0, 1fr)' }} aria-label={point.meter_id}>
                <header style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', flexWrap: 'wrap' }}>
                    <div>
                        <h3 style={{ margin: 0, overflowWrap: 'anywhere' }}>{point.meter_id}</h3>
                        <small className="muted">{point.zev_name}</small>
                    </div>
                    <div className="actions-row actions-row-wrap">
                        {eligible.history && <BehindMeterBadge />}
                        <MeteringDataLink meteringPointId={point.metering_point} />
                    </div>
                </header>

                {historySource?.status === 'reconnect_required' && (
                    <div className="warning-banner" role="alert">
                        <strong>{t('supplementary.reconnect.title')}</strong>
                        <p style={{ margin: '0.25rem 0 0' }}>{historySource.last_error || t('supplementary.reconnect.body')}</p>
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
                            onOpenSource={(source) => setOpenSourceId(source.id)}
                            onConnect={(capability) => setConnecting([capability])}
                        />
                        {unconnected.length > 0 && (
                            <div className="actions-row actions-row-wrap">
                                <button
                                    type="button"
                                    className="button button-primary"
                                    disabled={isImpersonating}
                                    title={isImpersonating ? t('account.impersonationRestrictions') : undefined}
                                    onClick={() => setConnecting(unconnected)}
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
                    available={unconnected}
                    initial={connecting}
                    sources={sources}
                    onClose={() => setConnecting(null)}
                />
            )}
            {openSource && (
                <SourceDialog
                    subject={point.meter_id}
                    source={openSource}
                    sources={sources}
                    eligible={eligible}
                    confirm={confirm}
                    canManage
                    onClose={() => setOpenSourceId(null)}
                />
            )}
        </>
    )
}
