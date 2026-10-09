import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
    deleteSupplementarySource,
    disconnectSupplementarySource,
    purgeSupplementaryReadings,
    rotateSupplementaryPushToken,
    syncSupplementarySource,
    testSupplementarySource,
    updateSupplementarySource,
} from '../../lib/api/supplementary'
import { formatApiError } from '../../lib/api/errors'
import { queryKeys } from '../../lib/api/queryKeys'
import { formatDateTime, useAppSettings } from '../../lib/appSettings'
import { useToast } from '../../lib/toast'
import type { EligibleMeteringPoint, SupplementarySource } from '../../types/api'
import { CsvImport } from '../supplementary/CsvImport'
import { PushTokenPanel } from '../supplementary/PushTokenPanel'
import { ReconciliationSummary } from '../supplementary/ReconciliationSummary'
import { SourceStatusBadge } from '../supplementary/SourceStatusBadge'

type ConfirmOptions = {
    title: string
    message: string
    confirmText: string
    isDangerous: boolean
    onConfirm: () => void | Promise<void>
}

interface Props {
    point: EligibleMeteringPoint
    source: SupplementarySource
    confirm: (options: ConfirmOptions) => void
}

/** One connected source, with everything its owner can do to it. The credential is never shown. */
export function SupplementarySourceCard({ point, source, confirm }: Props) {
    const { t } = useTranslation()
    const { settings } = useAppSettings()
    const { pushToast } = useToast()
    const queryClient = useQueryClient()

    const [replacing, setReplacing] = useState(false)
    const [newKey, setNewKey] = useState('')
    const [newId, setNewId] = useState(source.external_id)
    const [token, setToken] = useState<string | null>(null)
    const [showCsv, setShowCsv] = useState(false)

    const isSolar = source.provider === 'solar_manager'
    const disconnected = !source.enabled

    function refresh() {
        void queryClient.invalidateQueries({ queryKey: queryKeys.metering.supplementarySources() })
        void queryClient.invalidateQueries({ queryKey: queryKeys.metering.supplementaryEligible() })
        void queryClient.invalidateQueries({ queryKey: ['metering', 'dashboard-summary'] })
    }
    const onError = (error: unknown) => pushToast(formatApiError(error, t('common.error')), 'error')

    const test = useMutation({
        mutationFn: () => testSupplementarySource(source.id),
        onSuccess: () => pushToast(t('supplementary.actions.testOk'), 'success'),
        onError,
        onSettled: refresh,
    })
    const sync = useMutation({
        mutationFn: () => syncSupplementarySource(source.id),
        onSuccess: () => pushToast(t('supplementary.actions.syncQueued'), 'success'),
        onError: (error: any) =>
            pushToast(
                error?.response?.status === 429 ? t('supplementary.actions.syncCooldown') : formatApiError(error, t('common.error')),
                error?.response?.status === 429 ? 'info' : 'error',
            ),
        onSettled: refresh,
    })
    const replaceKey = useMutation({
        mutationFn: () =>
            updateSupplementarySource(source.id, {
                api_key: newKey.trim(),
                external_id: newId.trim(),
                enabled: true,
            }),
        onSuccess: () => {
            setReplacing(false)
            setNewKey('')
            pushToast(t('supplementary.actions.keyReplaced'), 'success')
        },
        onError,
        onSettled: refresh,
    })
    const disconnect = useMutation({
        mutationFn: () => disconnectSupplementarySource(source.id),
        onSuccess: () => pushToast(t('supplementary.actions.disconnected'), 'success'),
        onError,
        onSettled: refresh,
    })
    const purge = useMutation({
        mutationFn: () => purgeSupplementaryReadings(source.id),
        onSuccess: (data) => pushToast(t('supplementary.actions.dataDeleted', { count: data.deleted }), 'success'),
        onError,
        onSettled: refresh,
    })
    const remove = useMutation({
        mutationFn: () => deleteSupplementarySource(source.id),
        onSuccess: () => pushToast(t('supplementary.actions.removed'), 'success'),
        onError,
        onSettled: refresh,
    })
    const rotate = useMutation({
        mutationFn: () => rotateSupplementaryPushToken(source.id),
        onSuccess: (data) => setToken(data.push_token),
        onError,
        onSettled: refresh,
    })

    const busy = [test, sync, replaceKey, disconnect, purge, remove, rotate].some((m) => m.isPending)
    const dateTime = (value: string | null) => (value ? formatDateTime(value, settings) : t('supplementary.never'))

    return (
        <article className="card" style={{ display: 'grid', gap: '1rem', gridTemplateColumns: 'minmax(0, 1fr)' }} aria-label={point.meter_id}>
            <header style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', flexWrap: 'wrap' }}>
                <div>
                    <h3 style={{ margin: 0, overflowWrap: 'anywhere' }}>{point.meter_id}</h3>
                    <small className="muted">
                        {point.zev_name} · {t(`supplementary.provider.${source.provider}`)}
                        {source.label ? ` · ${source.label}` : ''}
                    </small>
                </div>
                <SourceStatusBadge status={source.status} />
            </header>

            {source.status === 'reconnect_required' && (
                <div className="warning-banner" role="alert">
                    <strong>{t('supplementary.reconnect.title')}</strong>
                    <p style={{ margin: '0.25rem 0 0' }}>{source.last_error || t('supplementary.reconnect.body')}</p>
                </div>
            )}
            {source.status === 'error' && source.last_error && (
                <div className="warning-banner" role="status">
                    <p style={{ margin: 0 }}>{source.last_error}</p>
                </div>
            )}
            {disconnected && <p className="muted" style={{ margin: 0 }}>{t('supplementary.disconnectedNote')}</p>}

            <dl style={{ display: 'grid', gridTemplateColumns: 'minmax(7rem, max-content) minmax(0, 1fr)', overflowWrap: 'anywhere', gap: '0.4rem 1rem', margin: 0 }}>
                {isSolar && (
                    <>
                        <dt className="muted">{t('supplementary.card.smId')}</dt>
                        <dd style={{ margin: 0 }}><code>{source.external_id}</code></dd>
                    </>
                )}
                {!isSolar && source.push_token_prefix && (
                    <>
                        <dt className="muted">{t('supplementary.card.token')}</dt>
                        <dd style={{ margin: 0 }}><code>ozs_{source.push_token_prefix}_…</code></dd>
                    </>
                )}
                <dt className="muted">{t('supplementary.card.lastSync')}</dt>
                <dd style={{ margin: 0 }}>{dateTime(source.last_success_at)}</dd>
                <dt className="muted">{t('supplementary.card.covered')}</dt>
                <dd style={{ margin: 0 }}>
                    {source.covers_from && source.synced_through
                        ? t('supplementary.card.coveredRange', {
                              from: formatDateTime(source.covers_from, settings),
                              to: formatDateTime(source.synced_through, settings),
                          })
                        : t('supplementary.card.noData')}
                </dd>
                <dt className="muted">{t('supplementary.card.reconciliation')}</dt>
                <dd style={{ margin: 0 }}><ReconciliationSummary reconciliation={source.reconciliation} /></dd>
            </dl>

            {token && <PushTokenPanel token={token} onDismiss={() => setToken(null)} />}

            {replacing && (
                <form
                    className="form-grid"
                    onSubmit={(event) => {
                        event.preventDefault()
                        replaceKey.mutate()
                    }}
                >
                    <label>
                        <span>{t('supplementary.modal.smId')}</span>
                        <input type="text" value={newId} onChange={(e) => setNewId(e.target.value)} maxLength={24} required autoComplete="off" />
                    </label>
                    <label>
                        <span>{t('supplementary.modal.apiKey')}</span>
                        <input
                            type="password"
                            value={newKey}
                            onChange={(e) => setNewKey(e.target.value)}
                            autoComplete="new-password"
                            spellCheck={false}
                            required
                        />
                        <small className="muted">{t('supplementary.modal.apiKeyHint')}</small>
                    </label>
                    <div className="actions-row actions-row-wrap grid-span-full">
                        <button type="submit" className="button button-primary" disabled={replaceKey.isPending || !newKey.trim()}>
                            {replaceKey.isPending ? t('common.saving') : t('supplementary.actions.saveKey')}
                        </button>
                        <button type="button" className="button button-secondary" onClick={() => setReplacing(false)}>
                            {t('common.cancel')}
                        </button>
                    </div>
                </form>
            )}

            {showCsv && !disconnected && <CsvImport sourceId={source.id} />}

            <div className="actions-row actions-row-wrap">
                {isSolar && !disconnected && (
                    <>
                        <button type="button" className="button button-secondary button-compact" disabled={busy} onClick={() => test.mutate()}>
                            {test.isPending ? t('supplementary.actions.testing') : t('supplementary.actions.test')}
                        </button>
                        <button
                            type="button"
                            className="button button-secondary button-compact"
                            disabled={busy || source.status === 'reconnect_required'}
                            onClick={() => sync.mutate()}
                        >
                            {t('supplementary.actions.sync')}
                        </button>
                    </>
                )}
                {isSolar && (
                    <button type="button" className="button button-secondary button-compact" disabled={busy} onClick={() => setReplacing((open) => !open)}>
                        {disconnected || source.status === 'reconnect_required'
                            ? t('supplementary.actions.reconnect')
                            : t('supplementary.actions.replaceKey')}
                    </button>
                )}
                {!isSolar && (
                    <>
                        <button
                            type="button"
                            className="button button-secondary button-compact"
                            disabled={busy}
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
                        {!disconnected && (
                            <button type="button" className="button button-secondary button-compact" onClick={() => setShowCsv((open) => !open)}>
                                {t('supplementary.actions.importCsv')}
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
                                message: t('supplementary.confirm.disconnectMessage'),
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
                            title: t('supplementary.confirm.deleteDataTitle'),
                            message: t('supplementary.confirm.deleteDataMessage'),
                            confirmText: t('supplementary.actions.deleteData'),
                            isDangerous: true,
                            onConfirm: () => purge.mutate(),
                        })
                    }
                >
                    {t('supplementary.actions.deleteData')}
                </button>
                <button
                    type="button"
                    className="button button-danger button-compact"
                    disabled={busy}
                    onClick={() =>
                        confirm({
                            title: t('supplementary.confirm.removeTitle'),
                            message: t('supplementary.confirm.removeMessage'),
                            confirmText: t('supplementary.actions.remove'),
                            isDangerous: true,
                            onConfirm: () => remove.mutate(),
                        })
                    }
                >
                    {t('supplementary.actions.remove')}
                </button>
            </div>
        </article>
    )
}
