import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { FormModal } from '../../components/FormModal'
import { Notice } from '../../components/Notice'
import { queryKeys } from '../../lib/api/queryKeys'
import { fetchZevEligibleSources, listSupplementarySources } from '../../lib/api/supplementary'
import { useAuth } from '../../lib/auth'
import { useLiveEnabled } from '../../lib/live'
import { connectionPointSource } from '../../lib/supplementary'
import type { MeteringPoint, SupplementarySource } from '../../types/api'
import { LiveSourceDetails, type ConfirmOptions } from '../supplementary/LiveSourceDetails'
import { LiveSourceSection } from '../supplementary/LiveSourceSection'
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
 * The "Live data" action of a ZEV-operated metering point. A point without a live source opens the
 * connect dialog straight away; one with a source opens its status and actions. One dialog at a
 * time, so nothing but a confirmation ever opens over another dialog.
 */
export function PointLiveDialog({ point, setup, confirm, onClose }: { point: MeteringPoint; setup: Setup; confirm: Confirm; onClose: () => void }) {
    const { t } = useTranslation()
    // Decided once, when the dialog opens: connecting a source makes the point "have" one while its
    // one-time token is still on screen, and the connect dialog must not turn into the status dialog then.
    const [connecting] = useState(() => !setup.zevEligibleByPoint.get(point.id)?.sources.live)
    if (connecting) {
        return <SupplementarySourceModal mode="zev-live" point={{ metering_point: point.id, meter_id: point.meter_id, zev: point.zev }} onClose={onClose} />
    }
    return (
        <FormModal isOpen title={t('supplementary.live.dialogTitle', { meter: point.meter_id })} onClose={onClose}>
            <LiveSourceSection
                bare
                meteringPointId={point.id}
                meterId={point.meter_id}
                zevId={point.zev}
                heldBy="zev"
                sources={setup.sourcesQuery.data}
                sourcesUnavailable={setup.sourcesQuery.isLoading ? 'loading' : setup.sourcesQuery.isError ? 'error' : undefined}
                onRetrySources={() => void setup.sourcesQuery.refetch()}
                confirm={confirm}
                onGone={onClose}
            />
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
    const [connecting, setConnecting] = useState(false)
    const { sourcesQuery, zevEligibleQuery } = setup

    const source: SupplementarySource | undefined = connectionPointSource(sourcesQuery.data, zevId)
    const eligibility = zevEligibleQuery.data?.connection_point
    // A manager sees the card while the ZEV can have a connection point; a viewer only once one exists.
    const exists = !!source || !!eligibility?.source
    const offered = canWrite && !!eligibility?.available
    if (!setup.liveOn || (!exists && !offered)) return null

    let body
    if (source) {
        body = <LiveSourceDetails source={source} confirm={confirm} canManage={canWrite} />
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
            {connecting && <SupplementarySourceModal mode="connection-point" zevId={zevId} onClose={() => setConnecting(false)} />}
        </>
    )
}

