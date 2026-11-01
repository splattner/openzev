import { useEffect, useState, type Ref } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faEllipsis } from '@fortawesome/free-solid-svg-icons'
import { ActionMenu, type ActionMenuItem } from '../../components/ActionMenu'
import { Disclosure } from '../../components/Disclosure'
import { DetailPane } from '../../components/DetailPane'
import { FormModal } from '../../components/FormModal'
import { useAuth } from '../../lib/auth'
import { formatDateTime, useAppSettings } from '../../lib/appSettings'
import { capabilityProblem, sourceFor } from '../../lib/supplementary'
import type { SupplementarySource } from '../../types/api'
import { CsvImport } from './CsvImport'
import { CapabilityProblemText } from './CapabilityProblemText'
import { PushEndpoints, PushTokenPanel } from './PushTokenPanel'
import { ReconciliationSummary } from './ReconciliationSummary'
import { useSourceActions, type ConfirmOptions } from './useSourceActions'

export type { ConfirmOptions } from './useSourceActions'

/** Which capabilities the source's metering point can have (its eligibility); none for the connection point. */
export interface PointEligibility {
    history: boolean
    live: boolean
    forecast?: boolean
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
    /** A new Solar Manager key has been typed and not saved: the host asks before it lets go of the source. */
    onDirtyChange?: (dirty: boolean) => void
    /** Name the source at the top of the body, for a host whose own title does not (a dialog). */
    identity?: boolean
    /**
     * Somebody else's source, seen by a manager of the community: they switch it off or on, delete its data or
     * remove it, never test it, change its key or its capabilities (the account is the participant's). `own` says
     * the signed-in user is that participant, who manages it on My metering points instead.
     */
    onBehalfOf?: { name: string | null; own: boolean }
}

const NO_CAPABILITY: PointEligibility = { history: false, live: false }

/**
 * Everything about one source: what it is, how it is doing and what its owner can do to it. It is the
 * body of `SourceDialog`, and of a host that already is a dialog. The one-time token of a rotation
 * lives here, above everything a refetch can change, and the credential is never shown.
 */
export function SourceDetails({ source, sources, eligible = NO_CAPABILITY, confirm, canManage, onGone, onDirtyChange, identity = false, onBehalfOf }: DetailsProps) {
    const { t } = useTranslation()
    const { isImpersonating } = useAuth()
    const { settings } = useAppSettings()

    const [replacing, setReplacing] = useState(false)
    const [newKey, setNewKey] = useState('')
    const [newId, setNewId] = useState(source.external_id)
    const [token, setToken] = useState<string | null>(null)
    const [showCsv, setShowCsv] = useState(false)
    const keyDraft = replacing && newKey.trim() !== ''
    useEffect(() => {
        onDirtyChange?.(keyDraft)
        // Leaving with a draft in it is no longer a draft the host has to guard.
        return () => onDirtyChange?.(false)
    }, [keyDraft, onDirtyChange])

    const { test, sync, replaceKey, setEnabled, disconnect, purge, remove, rotate, revoke, capability, busy } = useSourceActions(source, {
        onToken: setToken,
        onGone,
        onKeyReplaced: () => {
            setReplacing(false)
            setNewKey('')
        },
    })

    const isSolar = source.provider === 'solar_manager'
    const isPush = source.provider === 'push'
    const isForecastSolar = source.provider === 'forecast_solar'
    const disconnected = !source.enabled
    const hasHistory = source.provides_history
    const dateTime = (value: string | null) => (value ? formatDateTime(value, settings) : t('supplementary.never'))

    // Both providers take the other capability on the same connection; Solar Manager reuses its stored key.
    const canAddLive =
        !disconnected && eligible.live && !source.provides_live && !!source.metering_point && !sourceFor(sources, source.metering_point, 'live')
    const canAddHistory =
        !disconnected && eligible.history && !source.provides_history && source.held_by === 'participant' &&
        !!source.metering_point && !sourceFor(sources, source.metering_point, 'history')
    // Solar Manager also reads the installation's own forecast with the stored key.
    const canAddForecast =
        !disconnected && isSolar && !!eligible.forecast && !source.provides_forecast && !!source.metering_point &&
        !sourceFor(sources, source.metering_point, 'forecast')
    // A source must keep one capability: stopping one is only offered while the others remain.
    const capabilityCount = [source.provides_history, source.provides_live, source.provides_forecast].filter(Boolean).length
    const canStopLive = source.provides_live && capabilityCount > 1
    const canStopHistory = source.provides_history && capabilityCount > 1
    const canStopForecast = source.provides_forecast && capabilityCount > 1

    const confirmCapability = (options: Omit<ConfirmOptions, 'isDangerous'>) => confirm({ ...options, isDangerous: false })

    // One visible action: what keeps the connection working right now. Everything else is in the menu.
    const limited = !!onBehalfOf
    const needsNewKey = !limited && isSolar && (disconnected || source.status === 'reconnect_required')
    const canSync = !limited && (isSolar || isForecastSolar) && !disconnected && (hasHistory || source.provides_forecast) && source.status !== 'reconnect_required'
    const blocked = busy || isImpersonating
    const section = {
        connection: t('supplementary.source.menu.connection'),
        data: t('supplementary.source.menu.data'),
        end: t('supplementary.source.menu.end'),
    }
    const fullMenu: ActionMenuItem[] = []
    const item = (entry: ActionMenuItem) => fullMenu.push(entry)
    if ((isSolar || isForecastSolar) && !disconnected) {
        item({ key: 'test', section: section.connection, label: test.isPending ? t('supplementary.actions.testing') : t('supplementary.actions.test'), disabled: busy, onClick: () => test.mutate() })
    }
    if (isSolar && !needsNewKey) {
        item({ key: 'replace-key', section: section.connection, label: t('supplementary.actions.replaceKey'), disabled: busy, onClick: () => setReplacing(true) })
    }
    if (isPush && hasHistory && !disconnected) {
        item({ key: 'import-csv', section: section.connection, label: t('supplementary.actions.importCsv'), onClick: () => setShowCsv(true) })
    }
    if (isPush) {
        item({
            key: 'rotate', section: section.connection, label: t('supplementary.actions.rotate'), disabled: blocked,
            onClick: () => confirm({
                title: t('supplementary.confirm.rotateTitle'),
                message: t('supplementary.confirm.rotateMessage'),
                confirmText: t('supplementary.actions.rotate'),
                isDangerous: false,
                onConfirm: () => rotate.mutate(),
            }),
        })
    }
    if (isPush && source.push_token_prefix) {
        item({
            key: 'revoke', section: section.connection, label: t('supplementary.live.revoke'), disabled: busy,
            onClick: () => confirm({
                title: t('supplementary.live.confirm.revokeTitle'),
                message: t('supplementary.live.confirm.revokeMessage'),
                confirmText: t('supplementary.live.revoke'),
                isDangerous: false,
                onConfirm: () => revoke.mutate(),
            }),
        })
    }
    if (!disconnected) {
        item({
            key: 'disconnect', section: section.connection, label: t('supplementary.actions.disconnect'), disabled: busy,
            onClick: () => confirm({
                title: t('supplementary.confirm.disconnectTitle'),
                message: t(hasHistory ? 'supplementary.confirm.disconnectMessage' : source.provides_live ? 'supplementary.live.confirm.disconnectMessage' : 'supplementary.forecast.confirm.disconnectMessage'),
                confirmText: t('supplementary.actions.disconnect'),
                isDangerous: false,
                onConfirm: () => disconnect.mutate(),
            }),
        })
    }
    if (canAddLive) {
        item({
            key: 'add-live', section: section.data, label: t('supplementary.live.alsoSend'), disabled: blocked,
            onClick: () => confirmCapability({
                title: t('supplementary.live.confirm.alsoSendTitle'),
                message: `${t('supplementary.consent.liveVisible')} ${t('supplementary.consent.liveNotBilling')}`,
                confirmText: t('supplementary.live.alsoSend'),
                onConfirm: () => capability.mutate({ provides_live: true, consent: true }),
            }),
        })
    }
    if (canAddHistory) {
        item({
            key: 'add-history', section: section.data, label: t('supplementary.source.alsoHistory'), disabled: blocked,
            onClick: () => confirmCapability({
                title: t('supplementary.source.confirm.alsoHistoryTitle'),
                message: `${t('supplementary.consent.stored')} ${t('supplementary.consent.notBilling')}`,
                confirmText: t('supplementary.source.alsoHistory'),
                onConfirm: () => capability.mutate({ provides_history: true, consent: true }),
            }),
        })
    }
    if (canAddForecast) {
        item({
            key: 'add-forecast', section: section.data, label: t('supplementary.forecast.alsoUse'), disabled: blocked,
            onClick: () => confirmCapability({
                title: t('supplementary.forecast.confirm.alsoTitle'),
                message: t('supplementary.forecast.confirm.alsoMessage'),
                confirmText: t('supplementary.forecast.alsoUse'),
                onConfirm: () => capability.mutate({ provides_forecast: true, consent: true }),
            }),
        })
    }
    if (canStopForecast) {
        item({
            key: 'stop-forecast', section: section.data, label: t('supplementary.forecast.stop'), disabled: busy,
            onClick: () => confirmCapability({
                title: t('supplementary.forecast.confirm.stopTitle'),
                message: t('supplementary.forecast.confirm.stopMessage'),
                confirmText: t('supplementary.forecast.stop'),
                onConfirm: () => capability.mutate({ provides_forecast: false }),
            }),
        })
    }
    if (canStopLive) {
        item({
            key: 'stop-live', section: section.data, label: t('supplementary.live.stop'), disabled: busy,
            onClick: () => confirmCapability({
                title: t('supplementary.live.confirm.stopTitle'),
                message: t('supplementary.live.confirm.stopMessage'),
                confirmText: t('supplementary.live.stop'),
                onConfirm: () => capability.mutate({ provides_live: false }),
            }),
        })
    }
    if (canStopHistory) {
        item({
            key: 'stop-history', section: section.data, label: t('supplementary.source.stopHistory'), disabled: busy,
            onClick: () => confirmCapability({
                title: t('supplementary.source.confirm.stopHistoryTitle'),
                message: t('supplementary.source.confirm.stopHistoryMessage'),
                confirmText: t('supplementary.source.stopHistory'),
                onConfirm: () => capability.mutate({ provides_history: false }),
            }),
        })
    }
    if (source.provides_history) {
        item({
            key: 'delete-data', section: section.end, label: t('supplementary.actions.deleteData'), danger: true, disabled: busy,
            onClick: () => confirm({
                title: t('supplementary.confirm.deleteDataTitle'),
                message: t('supplementary.confirm.deleteDataMessage'),
                confirmText: t('supplementary.actions.deleteData'),
                isDangerous: true,
                onConfirm: () => purge.mutate(),
            }),
        })
    }
    item({
        key: 'remove', section: section.end, label: t('supplementary.actions.remove'), danger: true, disabled: busy,
        onClick: () => confirm({
            title: t('supplementary.confirm.removeTitle'),
            message: t(hasHistory ? 'supplementary.confirm.removeMessage' : source.provides_live ? 'supplementary.live.confirm.removeMessage' : 'supplementary.forecast.confirm.removeMessage'),
            confirmText: t('supplementary.actions.remove'),
            isDangerous: true,
            onConfirm: () => remove.mutate(),
        }),
    })

    // Somebody else's source: the manager's own rights only (switch off or on, delete the data, remove).
    const name = onBehalfOf?.name ?? ''
    const limitedMenu: ActionMenuItem[] = [
        {
            key: 'toggle', section: section.connection, label: t(source.enabled ? 'supplementary.owner.disable' : 'supplementary.owner.enable'), disabled: busy,
            onClick: () => setEnabled.mutate(!source.enabled),
        },
        ...(source.provides_history ? [{
            key: 'delete-data', section: section.end, label: t('supplementary.actions.deleteData'), danger: true, disabled: busy,
            onClick: () => confirm({
                title: t('supplementary.confirm.deleteDataTitle'),
                message: t('supplementary.owner.deleteDataMessage', { name }),
                confirmText: t('supplementary.actions.deleteData'),
                isDangerous: true,
                onConfirm: () => purge.mutate(),
            }),
        }] : []),
        {
            key: 'remove', section: section.end, label: t('supplementary.actions.remove'), danger: true, disabled: busy,
            onClick: () => confirm({
                title: t('supplementary.confirm.removeTitle'),
                message: t('supplementary.owner.removeMessage', { name }),
                confirmText: t('supplementary.actions.remove'),
                isDangerous: true,
                onConfirm: () => remove.mutate(),
            }),
        },
    ]
    const menu = limited ? limitedMenu : fullMenu

    const capabilities = { history: source.provides_history, live: source.provides_live }
    const hasTechnical = !limited && (isSolar || (isPush && !!source.push_token_prefix))

    return (
        <div className="source-details">
            {identity && (
                <p className="m-0"><strong>{t(`supplementary.provider.${source.provider}`)}{source.label ? ` · ${source.label}` : ''}</strong></p>
            )}
            {source.status === 'reconnect_required' && (
                <div className="warning-banner" role="alert">
                    <strong>{t('supplementary.reconnect.title')}</strong>
                    <p className="m-0 mt-05">{source.last_error || t('supplementary.reconnect.body')}</p>
                </div>
            )}
            {source.status === 'error' && source.last_error && (
                <div className="warning-banner" role="status">
                    <p className="m-0">{source.last_error}</p>
                </div>
            )}
            {disconnected && <p className="muted m-0">{t('supplementary.disconnectedNote')}</p>}
            {onBehalfOf && (
                <p className="muted m-0">
                    {onBehalfOf.own
                        ? <Link to="/me/metering-points">{t('supplementary.owner.manageOwn')}</Link>
                        : t('supplementary.owner.readOnlyNote', { name: onBehalfOf.name ?? '' })}
                </p>
            )}

            {canManage && (
                <div className="actions-row actions-row-wrap">
                    {needsNewKey && (
                        <button type="button" className="button button-secondary" disabled={busy} onClick={() => setReplacing(true)}>
                            {t('supplementary.actions.reconnect')}
                        </button>
                    )}
                    {canSync && (
                        <button type="button" className="button button-secondary" disabled={busy} onClick={() => sync.mutate()}>
                            {t(hasHistory ? 'supplementary.actions.sync' : 'supplementary.forecast.refresh')}
                        </button>
                    )}
                    <ActionMenu
                        iconOnly
                        compact={false}
                        label={t('supplementary.source.moreActions')}
                        icon={<FontAwesomeIcon icon={faEllipsis} fixedWidth />}
                        items={menu}
                    />
                </div>
            )}
            {canManage && isImpersonating && <small className="muted">{t('account.impersonationRestrictions')}</small>}

            {token && <PushTokenPanel token={token} onDismiss={() => setToken(null)} capabilities={capabilities} />}

            {replacing && canManage && (
                <form
                    className="form-grid form-grid-start"
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
                        <button type="button" className="button button-secondary" onClick={() => { setReplacing(false); setNewKey('') }}>
                            {t('common.cancel')}
                        </button>
                        <button type="submit" className="button button-primary" disabled={replaceKey.isPending || !newKey.trim()}>
                            {replaceKey.isPending ? t('common.saving') : t('supplementary.actions.saveKey')}
                        </button>
                    </div>
                </form>
            )}

            {showCsv && !disconnected && canManage && <CsvImport sourceId={source.id} />}

            {source.provides_history && (
                <section className="source-section">
                    <h3>{t('supplementary.capability.history')}</h3>
                    <CapabilityProblemText problem={capabilityProblem(source, 'history')} />
                    <dl className="source-facts">
                        <dt className="muted">{t('supplementary.card.lastSync')}</dt>
                        <dd>{dateTime(source.last_success_at)}</dd>
                        <dt className="muted">{t('supplementary.card.covered')}</dt>
                        <dd>
                            {source.covers_from && source.synced_through
                                ? t('supplementary.card.coveredRange', {
                                      from: formatDateTime(source.covers_from, settings),
                                      to: formatDateTime(source.synced_through, settings),
                                  })
                                : t('supplementary.card.noData')}
                        </dd>
                        <dt className="muted">{t('supplementary.card.reconciliation')}</dt>
                        <dd><ReconciliationSummary reconciliation={source.reconciliation} /></dd>
                    </dl>
                </section>
            )}
            {source.provides_live && (
                <section className="source-section">
                    <h3>{t('supplementary.capability.live')}</h3>
                    <CapabilityProblemText problem={capabilityProblem(source, 'live')} />
                    <dl className="source-facts">
                        <dt className="muted">{t('supplementary.live.lastValue')}</dt>
                        <dd>{dateTime(source.live_last_seen_at)}</dd>
                    </dl>
                </section>
            )}
            {source.provides_forecast && (
                <section className="source-section">
                    <h3>{t('supplementary.capability.forecast')}</h3>
                    <CapabilityProblemText problem={capabilityProblem(source, 'forecast')} />
                    {(source.provider === 'forecast_solar' || !source.provides_history) && (
                        <dl className="source-facts">
                            <dt className="muted">{t('supplementary.forecast.lastUpdate')}</dt>
                            <dd>{dateTime(source.last_success_at)}</dd>
                        </dl>
                    )}
                </section>
            )}

            {hasTechnical && (
                <Disclosure summary={t('supplementary.source.technical')}>
                    <div className="source-technical">
                        <dl className="source-facts">
                            {isSolar && (
                                <>
                                    <dt className="muted">{t('supplementary.card.smId')}</dt>
                                    <dd>{source.external_id}</dd>
                                </>
                            )}
                            {isPush && source.push_token_prefix && (
                                <>
                                    <dt className="muted">{t('supplementary.card.token')}</dt>
                                    <dd><code>ozs_{source.push_token_prefix}_…</code></dd>
                                    <dt className="muted">{t('supplementary.card.tokenIssued')}</dt>
                                    <dd>{dateTime(source.push_token_created_at)}</dd>
                                    <dt className="muted">{t('supplementary.card.tokenLastUsed')}</dt>
                                    <dd>{dateTime(source.push_token_last_used_at)}</dd>
                                </>
                            )}
                        </dl>
                        {isPush && !disconnected && !token && <PushEndpoints capabilities={capabilities} />}
                    </div>
                </Disclosure>
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
            <SourceDetails {...details} identity onGone={() => { details.onGone?.(); onClose() }} />
        </FormModal>
    )
}

interface PaneProps extends DetailsProps {
    /** What the source belongs to, for the title: the meter id. */
    subject: string
    onClose: () => void
    titleRef?: Ref<HTMLHeadingElement>
}

/**
 * One source beside the list it was opened from (SPEC-2026-10-ui-patterns §6.2, rule A): the same body as
 * the dialog, in a pane that is in flow on a wide screen and replaces the list on a narrow one. The host
 * keeps it open by the id in the URL, so a refetch of the source list cannot swap it away.
 */
export function SourcePane({ subject, onClose, titleRef, ...details }: PaneProps) {
    const { t } = useTranslation()
    const { source } = details
    const title = `${t(`supplementary.provider.${source.provider}`)}${source.label ? ` · ${source.label}` : ''}`
    const provides = (['history', 'live', 'forecast'] as const)
        .filter((capability) => source[`provides_${capability}`])
        .map((capability) => t(`supplementary.capability.${capability}`))
    return (
        <DetailPane tone="brand" title={title} subtitle={[subject, provides.join(', ')].filter(Boolean).join(' · ')} onClose={onClose} titleRef={titleRef}>
            <div className="detail-pane-body">
                <SourceDetails {...details} onGone={() => { details.onGone?.(); onClose() }} />
            </div>
        </DetailPane>
    )
}
