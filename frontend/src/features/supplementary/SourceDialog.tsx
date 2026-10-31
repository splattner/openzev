import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Disclosure } from '../../components/Disclosure'
import { FormModal } from '../../components/FormModal'
import { useAuth } from '../../lib/auth'
import { formatDateTime, useAppSettings } from '../../lib/appSettings'
import { sourceFor } from '../../lib/supplementary'
import type { SupplementarySource } from '../../types/api'
import { CsvImport } from './CsvImport'
import { LiveStateBadge } from './LiveStateBadge'
import { PushEndpoints, PushTokenPanel } from './PushTokenPanel'
import { ReconciliationSummary } from './ReconciliationSummary'
import { SourceStatusBadge } from './SourceStatusBadge'
import { useSourceActions, type ConfirmOptions } from './useSourceActions'

export type { ConfirmOptions } from './useSourceActions'

/** Which capabilities the source's metering point can have (its eligibility); none for the connection point. */
export interface PointEligibility {
    history: boolean
    live: boolean
}

interface DetailsProps {
    source: SupplementarySource
    /** The visible sources, to tell whether the other capability is still free on the meter. */
    sources?: SupplementarySource[]
    eligible?: PointEligibility
    confirm: (options: ConfirmOptions) => void
    /** The owner (holder, or a manager of a ZEV-held source) may act; a viewer only reads. */
    canManage: boolean
    /** The source is gone (deleted); the host closes. */
    onGone?: () => void
}

const NO_CAPABILITY: PointEligibility = { history: false, live: false }

/**
 * Everything about one source: what it is, how it is doing and what its owner can do to it. It is the
 * body of `SourceDialog`, and of a host that already is a dialog. The one-time token of a rotation
 * lives here, above everything a refetch can change, and the credential is never shown.
 */
export function SourceDetails({ source, sources, eligible = NO_CAPABILITY, confirm, canManage, onGone }: DetailsProps) {
    const { t } = useTranslation()
    const { isImpersonating } = useAuth()
    const { settings } = useAppSettings()

    const [replacing, setReplacing] = useState(false)
    const [newKey, setNewKey] = useState('')
    const [newId, setNewId] = useState(source.external_id)
    const [token, setToken] = useState<string | null>(null)
    const [showCsv, setShowCsv] = useState(false)

    const { test, sync, replaceKey, disconnect, purge, remove, rotate, revoke, capability, busy } = useSourceActions(source, {
        onToken: setToken,
        onGone,
        onKeyReplaced: () => {
            setReplacing(false)
            setNewKey('')
        },
    })

    const isSolar = source.provider === 'solar_manager'
    const isPush = source.provider === 'push'
    const disconnected = !source.enabled
    const hasHistory = source.provides_history
    const blockedTitle = isImpersonating ? t('account.impersonationRestrictions') : undefined
    const dateTime = (value: string | null) => (value ? formatDateTime(value, settings) : t('supplementary.never'))
    const small = 'button button-secondary button-compact'

    const canAddLive =
        isPush && !disconnected && eligible.live && !source.provides_live && !!source.metering_point && !sourceFor(sources, source.metering_point, 'live')
    const canAddHistory =
        isPush && !disconnected && eligible.history && !source.provides_history && source.held_by === 'participant' &&
        !!source.metering_point && !sourceFor(sources, source.metering_point, 'history')
    // A source must keep one capability: stopping one is only offered while the other remains.
    const canStopLive = source.provides_live && source.provides_history
    const canStopHistory = source.provides_history && source.provides_live

    const confirmCapability = (options: Omit<ConfirmOptions, 'isDangerous'>) => confirm({ ...options, isDangerous: false })

    return (
        <div style={{ display: 'grid', gap: '1rem', gridTemplateColumns: 'minmax(0, 1fr)' }}>
            {source.status === 'reconnect_required' && (
                <div className="warning-banner" role="alert">
                    <strong>{t('supplementary.reconnect.title')}</strong>
                    <p style={{ margin: '0.25rem 0 0' }}>{source.last_error || t('supplementary.reconnect.body')}</p>
                </div>
            )}
            {source.status === 'error' && source.last_error && (
                <div className="warning-banner" role="status">
                    <p className="m-0">{source.last_error}</p>
                </div>
            )}
            {disconnected && <p className="muted m-0">{t('supplementary.disconnectedNote')}</p>}

            <dl style={{ display: 'grid', gridTemplateColumns: 'minmax(7rem, max-content) minmax(0, 1fr)', overflowWrap: 'anywhere', gap: '0.4rem 1rem', margin: 0 }}>
                <dt className="muted">{t('supplementary.source.provider')}</dt>
                <dd className="m-0">{t(`supplementary.provider.${source.provider}`)}</dd>
                {source.label && (
                    <>
                        <dt className="muted">{t('supplementary.live.name')}</dt>
                        <dd className="m-0">{source.label}</dd>
                    </>
                )}
                <dt className="muted">{t('supplementary.source.provides')}</dt>
                <dd className="m-0 actions-row actions-row-wrap">
                    {source.provides_history && <span className="badge badge-neutral">{t('supplementary.capability.history')}</span>}
                    {source.provides_live && <span className="badge badge-neutral">{t('supplementary.capability.live')}</span>}
                </dd>
                {source.provides_history && (
                    <>
                        <dt className="muted">{t('supplementary.source.status')}</dt>
                        <dd className="m-0"><SourceStatusBadge status={source.status} /></dd>
                    </>
                )}
                {source.provides_live && (
                    <>
                        <dt className="muted">{t('supplementary.live.state')}</dt>
                        <dd className="m-0">{source.live_state ? <LiveStateBadge state={source.live_state} /> : '—'}</dd>
                        <dt className="muted">{t('supplementary.live.lastValue')}</dt>
                        <dd className="m-0">{dateTime(source.live_last_seen_at)}</dd>
                    </>
                )}
                {isSolar && (
                    <>
                        <dt className="muted">{t('supplementary.card.smId')}</dt>
                        <dd className="m-0"><code>{source.external_id}</code></dd>
                    </>
                )}
                {isPush && source.push_token_prefix && (
                    <>
                        <dt className="muted">{t('supplementary.card.token')}</dt>
                        <dd className="m-0"><code>ozs_{source.push_token_prefix}_…</code></dd>
                        <dt className="muted">{t('supplementary.card.tokenIssued')}</dt>
                        <dd className="m-0">{dateTime(source.push_token_created_at)}</dd>
                        <dt className="muted">{t('supplementary.card.tokenLastUsed')}</dt>
                        <dd className="m-0">{dateTime(source.push_token_last_used_at)}</dd>
                    </>
                )}
                {source.provides_history && (
                    <>
                        <dt className="muted">{t('supplementary.card.lastSync')}</dt>
                        <dd className="m-0">{dateTime(source.last_success_at)}</dd>
                        <dt className="muted">{t('supplementary.card.covered')}</dt>
                        <dd className="m-0">
                            {source.covers_from && source.synced_through
                                ? t('supplementary.card.coveredRange', {
                                      from: formatDateTime(source.covers_from, settings),
                                      to: formatDateTime(source.synced_through, settings),
                                  })
                                : t('supplementary.card.noData')}
                        </dd>
                        <dt className="muted">{t('supplementary.card.reconciliation')}</dt>
                        <dd className="m-0"><ReconciliationSummary reconciliation={source.reconciliation} /></dd>
                    </>
                )}
            </dl>

            {token && <PushTokenPanel token={token} onDismiss={() => setToken(null)} capabilities={{ history: source.provides_history, live: source.provides_live }} />}
            {isPush && !disconnected && !token && (
                <Disclosure summary={t('supplementary.source.endpoints')}>
                    <div style={{ display: 'grid', gap: '0.75rem', paddingTop: '0.75rem' }}>
                        <PushEndpoints capabilities={{ history: source.provides_history, live: source.provides_live }} />
                    </div>
                </Disclosure>
            )}

            {replacing && canManage && (
                <form
                    className="form-grid"
                    onSubmit={(event) => {
                        event.preventDefault()
                        replaceKey.mutate({ apiKey: newKey, externalId: newId })
                    }}
                >
                    <label>
                        <span>{t('supplementary.modal.smId')}</span>
                        <input type="text" value={newId} onChange={(e) => setNewId(e.target.value)} maxLength={24} required autoComplete="off" />
                    </label>
                    <label>
                        <span>{t('supplementary.modal.apiKey')}</span>
                        <input type="password" value={newKey} onChange={(e) => setNewKey(e.target.value)} autoComplete="new-password" spellCheck={false} required />
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

            {showCsv && !disconnected && canManage && <CsvImport sourceId={source.id} />}

            {canManage && (
                <div className="actions-row actions-row-wrap">
                    {isSolar && !disconnected && (
                        <>
                            <button type="button" className={small} disabled={busy} onClick={() => test.mutate()}>
                                {test.isPending ? t('supplementary.actions.testing') : t('supplementary.actions.test')}
                            </button>
                            <button type="button" className={small} disabled={busy || source.status === 'reconnect_required'} onClick={() => sync.mutate()}>
                                {t('supplementary.actions.sync')}
                            </button>
                        </>
                    )}
                    {isSolar && (
                        <button type="button" className={small} disabled={busy} onClick={() => setReplacing((open) => !open)}>
                            {disconnected || source.status === 'reconnect_required' ? t('supplementary.actions.reconnect') : t('supplementary.actions.replaceKey')}
                        </button>
                    )}
                    {isPush && source.provides_history && !disconnected && (
                        <button type="button" className={small} onClick={() => setShowCsv((open) => !open)}>
                            {t('supplementary.actions.importCsv')}
                        </button>
                    )}
                    {canAddLive && (
                        <button
                            type="button"
                            className={small}
                            disabled={busy || isImpersonating}
                            title={blockedTitle}
                            onClick={() =>
                                confirmCapability({
                                    title: t('supplementary.live.confirm.alsoSendTitle'),
                                    message: `${t('supplementary.consent.liveVisible')} ${t('supplementary.consent.liveNotBilling')}`,
                                    confirmText: t('supplementary.live.alsoSend'),
                                    onConfirm: () => capability.mutate({ provides_live: true, consent: true }),
                                })
                            }
                        >
                            {t('supplementary.live.alsoSend')}
                        </button>
                    )}
                    {canAddHistory && (
                        <button
                            type="button"
                            className={small}
                            disabled={busy || isImpersonating}
                            title={blockedTitle}
                            onClick={() =>
                                confirmCapability({
                                    title: t('supplementary.source.confirm.alsoHistoryTitle'),
                                    message: `${t('supplementary.consent.stored')} ${t('supplementary.consent.notBilling')}`,
                                    confirmText: t('supplementary.source.alsoHistory'),
                                    onConfirm: () => capability.mutate({ provides_history: true, consent: true }),
                                })
                            }
                        >
                            {t('supplementary.source.alsoHistory')}
                        </button>
                    )}
                    {canStopLive && (
                        <button
                            type="button"
                            className={small}
                            disabled={busy}
                            onClick={() =>
                                confirmCapability({
                                    title: t('supplementary.live.confirm.stopTitle'),
                                    message: t('supplementary.live.confirm.stopMessage'),
                                    confirmText: t('supplementary.live.stop'),
                                    onConfirm: () => capability.mutate({ provides_live: false }),
                                })
                            }
                        >
                            {t('supplementary.live.stop')}
                        </button>
                    )}
                    {canStopHistory && (
                        <button
                            type="button"
                            className={small}
                            disabled={busy}
                            onClick={() =>
                                confirmCapability({
                                    title: t('supplementary.source.confirm.stopHistoryTitle'),
                                    message: t('supplementary.source.confirm.stopHistoryMessage'),
                                    confirmText: t('supplementary.source.stopHistory'),
                                    onConfirm: () => capability.mutate({ provides_history: false }),
                                })
                            }
                        >
                            {t('supplementary.source.stopHistory')}
                        </button>
                    )}
                    {isPush && (
                        <button
                            type="button"
                            className={small}
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
                    )}
                    {isPush && source.push_token_prefix && (
                        <button
                            type="button"
                            className={small}
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
                    {!disconnected && (
                        <button
                            type="button"
                            className={small}
                            disabled={busy}
                            onClick={() =>
                                confirm({
                                    title: t('supplementary.confirm.disconnectTitle'),
                                    message: t(hasHistory ? 'supplementary.confirm.disconnectMessage' : 'supplementary.live.confirm.disconnectMessage'),
                                    confirmText: t('supplementary.actions.disconnect'),
                                    isDangerous: false,
                                    onConfirm: () => disconnect.mutate(),
                                })
                            }
                        >
                            {t('supplementary.actions.disconnect')}
                        </button>
                    )}
                    {source.provides_history && (
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
                    )}
                    <button
                        type="button"
                        className="button button-danger button-compact"
                        disabled={busy}
                        onClick={() =>
                            confirm({
                                title: t('supplementary.confirm.removeTitle'),
                                message: t(hasHistory ? 'supplementary.confirm.removeMessage' : 'supplementary.live.confirm.removeMessage'),
                                confirmText: t('supplementary.actions.remove'),
                                isDangerous: true,
                                onConfirm: () => remove.mutate(),
                            })
                        }
                    >
                        {t('supplementary.actions.remove')}
                    </button>
                </div>
            )}
        </div>
    )
}

interface DialogProps extends DetailsProps {
    /** What the source belongs to, for the title: the meter id, or the grid connection point. */
    subject: string
    onClose: () => void
}

/**
 * One source in a dialog (SPEC-2026-10-ui-patterns rule 3/C: a detail opened from a card, with no list
 * beside it, is a dialog; confirmations are the only thing opened over it). The host keeps it open by
 * its own state and never by what the source list says, so a refetch cannot swap it away.
 */
export function SourceDialog({ subject, onClose, ...details }: DialogProps) {
    const { t } = useTranslation()
    return (
        <FormModal isOpen size="md" title={t('supplementary.source.title', { subject })} onClose={onClose}>
            <SourceDetails {...details} onGone={() => { details.onGone?.(); onClose() }} />
        </FormModal>
    )
}
