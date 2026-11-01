import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { FormModal } from '../../components/FormModal'
import { Notice } from '../../components/Notice'
import { queryKeys } from '../../lib/api/queryKeys'
import { fetchZevEligibleSources, listSupplementarySources } from '../../lib/api/supplementary'
import { formatDateTime, useAppSettings } from '../../lib/appSettings'
import { useAuth } from '../../lib/auth'
import { useLiveEnabled } from '../../lib/live'
import { connectionPointSource, sourceFor } from '../../lib/supplementary'
import type { MeteringPoint, SupplementarySource } from '../../types/api'
import { CapabilityRows } from '../supplementary/CapabilityRows'
import { LiveStateBadge } from '../supplementary/LiveStateBadge'
import { SourceDetails, SourceDialog, type ConfirmOptions } from '../supplementary/SourceDialog'
import { SupplementarySourceModal } from '../supplementary/SupplementarySourceModal'

type Confirm = (options: ConfirmOptions) => void

interface SetupArgs {
    zevId: string | undefined
    /** Manager or admin with write access to the selected ZEV. */
    canWrite: boolean
    isManagedScope: boolean
}

/**
 * What the metering-point page needs to set up live data: whether the instance has the live view on,
 * the sources of the ZEV (managers and viewers read them) and, for a manager, the points nobody holds
 * personally and the state of the connection point. All of it stays off while the live flag is off.
 */
export function useLiveSetup({ zevId, canWrite, isManagedScope }: SetupArgs) {
    const liveEnabled = useLiveEnabled({ enabled: isManagedScope })
    const liveOn = isManagedScope && liveEnabled.data === true
    const sourcesQuery = useQuery({
        queryKey: queryKeys.metering.supplementarySources(),
        queryFn: listSupplementarySources,
        enabled: liveOn,
    })
    const zevEligibleQuery = useQuery({
        queryKey: queryKeys.metering.supplementaryZevEligible(zevId ?? ''),
        queryFn: () => fetchZevEligibleSources(zevId as string),
        enabled: liveOn && canWrite && !!zevId,
        retry: false,
    })
    const zevEligibleByPoint = new Map((zevEligibleQuery.data?.metering_points ?? []).filter((entry) => entry.eligible_capabilities.includes('live')).map((entry) => [entry.metering_point, entry]))
    return { liveOn, sourcesQuery, zevEligibleQuery, zevEligibleByPoint }
}

type Setup = ReturnType<typeof useLiveSetup>

/**
 * The "Live data" action of a ZEV-operated metering point (live only: history belongs to participants).
 * A point without a live source opens the connect flow straight away; one with a source opens its row,
 * which opens the source's details. It is one dialog whose content changes with the user's own choices
 * (rows, details, connect) and never with the source list, so the one-time token of a new source stays
 * on screen while the lists refetch, and nothing but a confirmation opens over it.
 */
export function PointLiveDialog({ point, setup, confirm, onClose }: { point: MeteringPoint; setup: Setup; confirm: Confirm; onClose: () => void }) {
    const { t } = useTranslation()
    // Decided once, when the dialog opens.
    const [startsConnecting] = useState(() => !setup.zevEligibleByPoint.get(point.id)?.sources.live)
    const [view, setView] = useState<'rows' | 'source' | 'connect'>(startsConnecting ? 'connect' : 'rows')
    const { sourcesQuery } = setup
    const sources = sourcesQuery.data
    const liveSource = sourceFor(sources, point.id, 'live')

    if (view === 'connect') {
        return (
            <SupplementarySourceModal
                holder="zev"
                point={{ metering_point: point.id, meter_id: point.meter_id, zev: point.zev }}
                sources={sources}
                onClose={() => (startsConnecting ? onClose() : setView('rows'))}
            />
        )
    }
    return (
        <FormModal isOpen size="md" title={t(view === 'source' ? 'supplementary.source.title' : 'supplementary.live.dialogTitle', { meter: point.meter_id, subject: point.meter_id })} onClose={onClose}>
            {!sources ? (
                sourcesQuery.isError ? (
                    <Notice tone="error" onRetry={() => void sourcesQuery.refetch()}>{t('supplementary.section.loadError')}</Notice>
                ) : (
                    <p className="muted m-0">{t('common.loading')}</p>
                )
            ) : view === 'source' && liveSource ? (
                <div style={{ display: 'grid', gap: '1rem' }}>
                    <div>
                        <button type="button" className="button button-ghost button-compact" onClick={() => setView('rows')}>
                            {t('supplementary.modal.back')}
                        </button>
                    </div>
                    <SourceDetails source={liveSource} sources={sources} confirm={confirm} canManage onGone={onClose} />
                </div>
            ) : (
                <CapabilityRows
                    meteringPointId={point.id}
                    capabilities={['live']}
                    sources={sources}
                    zevHeld
                    onOpenSource={() => setView('source')}
                    onConnect={() => setView('connect')}
                />
            )}
        </FormModal>
    )
}


/**
 * The ZEV's grid connection point: one live source reporting the net power at the grid connection,
 * which lets the live view show how much the ZEV consumes. Only a physical ZEV has one (the backend
 * says so through `available` / `source`). Managers connect and manage it; viewers see its state.
 */
export function ConnectionPointCard({ zevId, setup, canWrite, confirm }: { zevId: string; setup: Setup; canWrite: boolean; confirm: Confirm }) {
    const { t } = useTranslation()
    const { isImpersonating } = useAuth()
    const { settings } = useAppSettings()
    const [connecting, setConnecting] = useState(false)
    const [detailsOpen, setDetailsOpen] = useState(false)
    const { sourcesQuery, zevEligibleQuery } = setup

    const source: SupplementarySource | undefined = connectionPointSource(sourcesQuery.data, zevId)
    const eligibility = zevEligibleQuery.data?.connection_point
    // A manager sees the card while the ZEV can have a connection point; a viewer only once one exists.
    const exists = !!source || !!eligibility?.source
    const offered = canWrite && !!eligibility?.available
    if (!setup.liveOn || (!exists && !offered)) return null

    let body
    if (source) {
        body = (
            <div className="actions-row actions-row-wrap">
                {source.live_state ? <LiveStateBadge state={source.live_state} /> : null}
                <small className="muted">
                    {t('supplementary.card.lastValueAt', { date: source.live_last_seen_at ? formatDateTime(source.live_last_seen_at, settings) : t('supplementary.never') })}
                </small>
                {canWrite && (
                    <button type="button" className="button button-secondary button-compact" onClick={() => setDetailsOpen(true)}>
                        {t('supplementary.connection.details')}
                    </button>
                )}
            </div>
        )
    } else if (sourcesQuery.isError) {
        body = (
            <Notice tone="error" onRetry={() => void sourcesQuery.refetch()} isRetrying={sourcesQuery.isFetching}>
                {t('supplementary.section.loadError')}
            </Notice>
        )
    } else if (exists) {
        body = <p className="muted m-0">{t('common.loading')}</p>
    } else {
        body = (
            <>
                <p className="muted m-0">{t('supplementary.connection.notConnected')}</p>
                <div className="actions-row actions-row-wrap">
                    <button
                        type="button"
                        className="button button-primary"
                        disabled={isImpersonating}
                        title={isImpersonating ? t('account.impersonationRestrictions') : undefined}
                        onClick={() => setConnecting(true)}
                    >
                        {t('supplementary.connection.connect')}
                    </button>
                </div>
            </>
        )
    }

    return (
        <>
            <section className="card" style={{ display: 'grid', gap: '0.75rem' }} aria-label={t('supplementary.connection.title')}>
                <div>
                    <h3 style={{ margin: 0 }}>{t('supplementary.connection.title')}</h3>
                    <small className="muted">{t('supplementary.connection.description')}</small>
                </div>
                {body}
            </section>
            {connecting && <SupplementarySourceModal holder="connection-point" zevId={zevId} onClose={() => setConnecting(false)} />}
            {detailsOpen && source && (
                <SourceDialog
                    subject={t('supplementary.connection.title')}
                    source={source}
                    sources={sourcesQuery.data}
                    confirm={confirm}
                    canManage={canWrite}
                    onClose={() => setDetailsOpen(false)}
                />
            )}
        </>
    )
}

