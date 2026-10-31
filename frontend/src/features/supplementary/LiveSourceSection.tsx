import { useState, type ReactNode } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../../lib/auth'
import { updateSupplementarySource } from '../../lib/api/supplementary'
import { formatApiError } from '../../lib/api/errors'
import { invalidateSourceQueries, sourceFor } from '../../lib/supplementary'
import { useToast } from '../../lib/toast'
import type { SupplementarySource } from '../../types/api'
import { LiveSourceDetails, type ConfirmOptions } from './LiveSourceDetails'
import { SupplementarySourceModal } from './SupplementarySourceModal'

interface Props {
    meteringPointId: string
    meterId: string
    zevId: string
    /** A participant's own meter, or one the ZEV operates (a manager's view). */
    heldBy: 'participant' | 'zev'
    zevName?: string
    /** The signed-in user's visible sources; `undefined` while they load or after they failed. */
    sources: SupplementarySource[] | undefined
    /** A source of this point is known to exist but the list is not here yet: Connect would be wrong. */
    sourcesUnavailable?: 'loading' | 'error'
    onRetrySources?: () => void
    confirm: (options: ConfirmOptions) => void
    /** The caller may create and change sources; a viewer only reads. */
    canManage?: boolean
    /** Without a card around it and with no way to connect (a host that already is a dialog). */
    bare?: boolean
    /** The live source was deleted. */
    onGone?: () => void
}

/**
 * The live data of one metering point. Without a live source: connect one, or, when the history
 * source is a push source, let that same token also carry live data. With one: its state and what
 * its owner can do to it. Live data is only shown, never used for billing.
 */
export function LiveSourceSection({
    meteringPointId,
    meterId,
    zevId,
    heldBy,
    zevName,
    sources,
    sourcesUnavailable,
    onRetrySources,
    confirm,
    canManage = true,
    bare = false,
    onGone,
}: Props) {
    const { t } = useTranslation()
    const { isImpersonating } = useAuth()
    const { pushToast } = useToast()
    const queryClient = useQueryClient()
    const [connecting, setConnecting] = useState(false)

    const liveSource = sourceFor(sources, meteringPointId, 'live')
    const historySource = sourceFor(sources, meteringPointId, 'history')
    const canShareToken = heldBy === 'participant' && historySource?.provider === 'push' && historySource.enabled

    const enableOnHistory = useMutation({
        mutationFn: () => updateSupplementarySource(historySource!.id, { provides_live: true, consent: true }),
        onSuccess: () => pushToast(t('supplementary.live.alsoSendDone'), 'success'),
        onError: (error) => pushToast(formatApiError(error, t('common.error')), 'error'),
        onSettled: () => invalidateSourceQueries(queryClient),
    })

    const blockedTitle = isImpersonating ? t('account.impersonationRestrictions') : undefined
    // The modal sits next to whatever shows, not inside it: creating a source swaps the content while
    // a push source's one-time token is still on screen, and the modal's state has to survive that.
    const modal = connecting ? (
        <SupplementarySourceModal
            mode={heldBy === 'zev' ? 'zev-live' : 'live'}
            point={{ metering_point: meteringPointId, meter_id: meterId, zev: zevId }}
            onClose={() => setConnecting(false)}
        />
    ) : null

    let content: ReactNode
    if (sourcesUnavailable && !sources) {
        content =
            sourcesUnavailable === 'loading' ? (
                <p className="muted m-0">{t('common.loading')}</p>
            ) : (
                <div className="error-banner" role="alert">
                    {t('supplementary.section.loadError')}
                    {onRetrySources && (
                        <button type="button" className="button button-secondary button-compact" onClick={onRetrySources} style={{ marginLeft: '0.75rem' }}>
                            {t('common.retry')}
                        </button>
                    )}
                </div>
            )
    } else if (liveSource) {
        content = <LiveSourceDetails source={liveSource} confirm={confirm} canManage={canManage} onGone={onGone} />
    } else {
        content = (
            <>
                <p className="muted m-0">{t(heldBy === 'zev' ? 'supplementary.live.zevNotConnected' : 'supplementary.live.notConnected')}</p>
                {canManage && !bare && (
                    <div className="actions-row actions-row-wrap">
                        {canShareToken && (
                            <button
                                type="button"
                                className="button button-primary"
                                disabled={isImpersonating || enableOnHistory.isPending}
                                title={blockedTitle}
                                onClick={() =>
                                    confirm({
                                        title: t('supplementary.live.confirm.alsoSendTitle'),
                                        message: `${t('supplementary.consent.liveVisible')} ${t('supplementary.consent.liveNotBilling')}`,
                                        confirmText: t('supplementary.live.alsoSend'),
                                        isDangerous: false,
                                        onConfirm: () => enableOnHistory.mutate(),
                                    })
                                }
                            >
                                {t('supplementary.live.alsoSend')}
                            </button>
                        )}
                        <button
                            type="button"
                            className={`button ${canShareToken ? 'button-secondary' : 'button-primary'}`}
                            disabled={isImpersonating}
                            title={blockedTitle}
                            onClick={() => setConnecting(true)}
                        >
                            {t('supplementary.live.connect')}
                        </button>
                    </div>
                )}
                {canShareToken && !bare && <small className="muted">{t('supplementary.live.alsoSendHint')}</small>}
            </>
        )
    }

    return (
        <>
            {bare ? (
                <div style={{ display: 'grid', gap: '0.75rem' }}>{content}</div>
            ) : (
                <article className="card" style={{ display: 'grid', gap: '0.75rem', gridTemplateColumns: 'minmax(0, 1fr)' }} aria-label={t('supplementary.live.sectionLabel', { meter: meterId })}>
                    <div>
                        <h3 style={{ margin: 0, overflowWrap: 'anywhere' }}>{meterId}</h3>
                        <small className="muted">
                            {t('supplementary.live.title')}
                            {zevName ? ` · ${zevName}` : ''}
                        </small>
                    </div>
                    {content}
                </article>
            )}
            {modal}
        </>
    )
}
