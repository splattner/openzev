import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../../lib/auth'
import {
    deleteSupplementarySource,
    disconnectSupplementarySource,
    revokeSupplementaryPushToken,
    rotateSupplementaryPushToken,
    updateSupplementarySource,
} from '../../lib/api/supplementary'
import { formatApiError } from '../../lib/api/errors'
import { formatDateTime, useAppSettings } from '../../lib/appSettings'
import { invalidateSourceQueries } from '../../lib/supplementary'
import { useToast } from '../../lib/toast'
import type { SupplementarySource } from '../../types/api'
import { LiveStateBadge } from './LiveStateBadge'
import { PushEndpoints, PushTokenPanel } from './PushTokenPanel'

export type ConfirmOptions = {
    title: string
    message: string
    confirmText: string
    isDangerous: boolean
    onConfirm: () => void | Promise<void>
}

interface Props {
    source: SupplementarySource
    confirm: (options: ConfirmOptions) => void
    /** The owner (holder, or a manager of a ZEV-held source) may act; a viewer only reads. */
    canManage: boolean
    /** The source is gone (deleted); a host that offers no way to connect again can close. */
    onGone?: () => void
}

/**
 * One live source: its freshness and what its owner can do to it. A source that only provides live
 * data can be rotated, revoked, disconnected or deleted; one that shares its token with history can
 * only stop live data (the rest belongs to the history card). The token is never shown again.
 */
export function LiveSourceDetails({ source, confirm, canManage, onGone }: Props) {
    const { t } = useTranslation()
    const { isImpersonating } = useAuth()
    const { settings } = useAppSettings()
    const { pushToast } = useToast()
    const queryClient = useQueryClient()
    const [token, setToken] = useState<string | null>(null)

    const shared = source.provides_history
    const isPush = source.provider === 'push'
    const disconnected = !source.enabled
    const refresh = () => invalidateSourceQueries(queryClient)
    const onError = (error: unknown) => pushToast(formatApiError(error, t('common.error')), 'error')

    const rotate = useMutation({
        mutationFn: () => rotateSupplementaryPushToken(source.id),
        onSuccess: (data) => setToken(data.push_token),
        onError,
        onSettled: refresh,
    })
    const revoke = useMutation({
        mutationFn: () => revokeSupplementaryPushToken(source.id),
        onSuccess: () => pushToast(t('supplementary.live.revoked'), 'success'),
        onError,
        onSettled: refresh,
    })
    const disconnect = useMutation({
        mutationFn: () => disconnectSupplementarySource(source.id),
        onSuccess: () => pushToast(t('supplementary.actions.disconnected'), 'success'),
        onError,
        onSettled: refresh,
    })
    const remove = useMutation({
        mutationFn: () => deleteSupplementarySource(source.id),
        onSuccess: () => {
            pushToast(t('supplementary.actions.removed'), 'success')
            onGone?.()
        },
        onError,
        onSettled: refresh,
    })
    const stop = useMutation({
        mutationFn: () => updateSupplementarySource(source.id, { provides_live: false }),
        onSuccess: () => pushToast(t('supplementary.live.stopped'), 'success'),
        onError,
        onSettled: refresh,
    })
    const busy = [rotate, revoke, disconnect, remove, stop].some((mutation) => mutation.isPending)
    const dateTime = (value: string | null) => (value ? formatDateTime(value, settings) : t('supplementary.never'))
    const blockedTitle = isImpersonating ? t('account.impersonationRestrictions') : undefined

    return (
        <>
            {disconnected && <p className="muted m-0">{t('supplementary.disconnectedNote')}</p>}
            <dl style={{ display: 'grid', gridTemplateColumns: 'minmax(7rem, max-content) minmax(0, 1fr)', overflowWrap: 'anywhere', gap: '0.4rem 1rem', margin: 0 }}>
                <dt className="muted">{t('supplementary.live.state')}</dt>
                <dd className="m-0">{source.live_state ? <LiveStateBadge state={source.live_state} /> : '—'}</dd>
                <dt className="muted">{t('supplementary.live.lastValue')}</dt>
                <dd className="m-0">{dateTime(source.live_last_seen_at)}</dd>
                {source.label && (
                    <>
                        <dt className="muted">{t('supplementary.live.name')}</dt>
                        <dd className="m-0">{source.label}</dd>
                    </>
                )}
                {isPush && source.push_token_prefix && (
                    <>
                        <dt className="muted">{t('supplementary.card.token')}</dt>
                        <dd className="m-0">
                            <code>ozs_{source.push_token_prefix}_…</code>
                        </dd>
                    </>
                )}
            </dl>

            {token && <PushTokenPanel token={token} onDismiss={() => setToken(null)} capabilities={{ history: shared, live: true }} />}
            {shared && isPush && !disconnected && (
                <div style={{ display: 'grid', gap: '0.75rem' }}>
                    <p className="muted m-0">{t('supplementary.live.sharedToken')}</p>
                    <PushEndpoints capabilities={{ history: false, live: true }} />
                </div>
            )}

            {canManage && (
                <div className="actions-row actions-row-wrap">
                    {shared ? (
                        <button
                            type="button"
                            className="button button-secondary button-compact"
                            disabled={busy}
                            onClick={() =>
                                confirm({
                                    title: t('supplementary.live.confirm.stopTitle'),
                                    message: t('supplementary.live.confirm.stopMessage'),
                                    confirmText: t('supplementary.live.stop'),
                                    isDangerous: false,
                                    onConfirm: () => stop.mutate(),
                                })
                            }
                        >
                            {t('supplementary.live.stop')}
                        </button>
                    ) : (
                        <>
                            {isPush && (
                                <>
                                    <button
                                        type="button"
                                        className="button button-secondary button-compact"
                                        disabled={busy || isImpersonating}
                                        title={blockedTitle}
                                        onClick={() =>
                                            confirm({
                                                title: t('supplementary.confirm.rotateTitle'),
                                                message: t('supplementary.confirm.rotateMessage'),
                                                confirmText: t('supplementary.actions.rotate'),
                                                isDangerous: false,
                                                onConfirm: () => rotate.mutate(),
                                            })
                                        }
                                    >
                                        {t('supplementary.actions.rotate')}
                                    </button>
                                    {source.push_token_prefix && (
                                        <button
                                            type="button"
                                            className="button button-secondary button-compact"
                                            disabled={busy}
                                            onClick={() =>
                                                confirm({
                                                    title: t('supplementary.live.confirm.revokeTitle'),
                                                    message: t('supplementary.live.confirm.revokeMessage'),
                                                    confirmText: t('supplementary.live.revoke'),
                                                    isDangerous: false,
                                                    onConfirm: () => revoke.mutate(),
                                                })
                                            }
                                        >
                                            {t('supplementary.live.revoke')}
                                        </button>
                                    )}
                                </>
                            )}
                            {!disconnected && (
                                <button
                                    type="button"
                                    className="button button-secondary button-compact"
                                    disabled={busy}
                                    onClick={() =>
                                        confirm({
                                            title: t('supplementary.confirm.disconnectTitle'),
                                            message: t('supplementary.live.confirm.disconnectMessage'),
                                            confirmText: t('supplementary.actions.disconnect'),
                                            isDangerous: false,
                                            onConfirm: () => disconnect.mutate(),
                                        })
                                    }
                                >
                                    {t('supplementary.actions.disconnect')}
                                </button>
                            )}
                            <button
                                type="button"
                                className="button button-danger button-compact"
                                disabled={busy}
                                onClick={() =>
                                    confirm({
                                        title: t('supplementary.confirm.removeTitle'),
                                        message: t('supplementary.live.confirm.removeMessage'),
                                        confirmText: t('supplementary.actions.remove'),
                                        isDangerous: true,
                                        onConfirm: () => remove.mutate(),
                                    })
                                }
                            >
                                {t('supplementary.actions.remove')}
                            </button>
                        </>
                    )}
                </div>
            )}
        </>
    )
}
