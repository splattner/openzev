import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { FormModal } from '../../components/FormModal'
import { formatApiError } from '../../lib/api/errors'
import { queryKeys } from '../../lib/api/queryKeys'
import {
    deleteSupplementarySource,
    listSupplementarySources,
    purgeSupplementaryReadings,
    updateSupplementarySource,
} from '../../lib/api/supplementary'
import { formatDateTime, useAppSettings } from '../../lib/appSettings'
import { STATUS_BADGE_CLASS, statusTone } from '../../lib/supplementary'
import { useToast } from '../../lib/toast'
import type { MeteringPoint } from '../../types/api'
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
    point: MeteringPoint
    /** A manager (not a viewer) of the ZEV: may switch the source off, delete its data or remove it. */
    canManage: boolean
    confirm: (options: ConfirmOptions) => void
}

/**
 * A chip on a metering point whose participant has connected an energy data source, and the panel
 * behind it. The owner sees the connection's state, never the credential, and cannot connect or
 * reconfigure it: the account belongs to the participant.
 */
export function SupplementarySourceStatus({ point, canManage, confirm }: Props) {
    const { t } = useTranslation()
    const [open, setOpen] = useState(false)
    const status = point.supplementary_source_status
    if (!status) return null

    return (
        <>
            <button
                type="button"
                className={`${STATUS_BADGE_CLASS[statusTone(status)]} badge-button`}
                onClick={() => setOpen(true)}
                aria-haspopup="dialog"
                title={t('supplementary.owner.chipHint')}
            >
                {t('supplementary.owner.chip', { status: t(`supplementary.status.${status}`) })}
            </button>
            {open && <SourcePanel point={point} canManage={canManage} confirm={confirm} onClose={() => setOpen(false)} />}
        </>
    )
}

function SourcePanel({ point, canManage, confirm, onClose }: Props & { onClose: () => void }) {
    const { t } = useTranslation()
    const { settings } = useAppSettings()
    const { pushToast } = useToast()
    const queryClient = useQueryClient()
    const sourcesQuery = useQuery({ queryKey: queryKeys.metering.supplementarySources(), queryFn: listSupplementarySources })
    const source = sourcesQuery.data?.find((candidate) => candidate.metering_point === point.id)

    function refresh() {
        void queryClient.invalidateQueries({ queryKey: queryKeys.metering.supplementarySources() })
        void queryClient.invalidateQueries({ queryKey: ['metering', 'points'] })
    }
    const onError = (error: unknown) => pushToast(formatApiError(error, t('common.error')), 'error')

    const toggle = useMutation({
        mutationFn: (enabled: boolean) => updateSupplementarySource(source!.id, { enabled }),
        onError,
        onSettled: refresh,
    })
    const purge = useMutation({
        mutationFn: () => purgeSupplementaryReadings(source!.id),
        onSuccess: (data) => pushToast(t('supplementary.actions.dataDeleted', { count: data.deleted }), 'success'),
        onError,
        onSettled: refresh,
    })
    const remove = useMutation({
        mutationFn: () => deleteSupplementarySource(source!.id),
        onSuccess: () => {
            pushToast(t('supplementary.actions.removed'), 'success')
            onClose()
        },
        onError,
        onSettled: refresh,
    })
    const busy = toggle.isPending || purge.isPending || remove.isPending

    return (
        <FormModal isOpen title={t('supplementary.owner.title', { meter: point.meter_id })} onClose={onClose}>
            {sourcesQuery.isLoading && <p className="muted">{t('common.loading')}</p>}
            {sourcesQuery.isError && <div className="error-banner" role="alert">{t('supplementary.section.loadError')}</div>}
            {source && (
                <div style={{ display: 'grid', gap: '1rem' }}>
                    <p className="muted" style={{ margin: 0 }}>{t('supplementary.owner.readOnlyNote', { name: source.participant_name })}</p>
                    <dl style={{ display: 'grid', gridTemplateColumns: 'minmax(7rem, max-content) minmax(0, 1fr)', overflowWrap: 'anywhere', gap: '0.4rem 1rem', margin: 0 }}>
                        <dt className="muted">{t('supplementary.owner.provider')}</dt>
                        <dd style={{ margin: 0 }}>{t(`supplementary.provider.${source.provider}`)}</dd>
                        <dt className="muted">{t('supplementary.owner.status')}</dt>
                        <dd style={{ margin: 0 }}><SourceStatusBadge status={source.status} /></dd>
                        <dt className="muted">{t('supplementary.card.lastSync')}</dt>
                        <dd style={{ margin: 0 }}>
                            {source.last_success_at ? formatDateTime(source.last_success_at, settings) : t('supplementary.never')}
                        </dd>
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
                    {source.last_error && <div className="warning-banner" role="status">{source.last_error}</div>}

                    {canManage && (
                        <div className="actions-row actions-row-wrap">
                            {source.enabled ? (
                                <button type="button" className="button button-secondary button-compact" disabled={busy} onClick={() => toggle.mutate(false)}>
                                    {t('supplementary.owner.disable')}
                                </button>
                            ) : (
                                <button type="button" className="button button-secondary button-compact" disabled={busy} onClick={() => toggle.mutate(true)}>
                                    {t('supplementary.owner.enable')}
                                </button>
                            )}
                            <button
                                type="button"
                                className="button button-danger button-compact"
                                disabled={busy}
                                onClick={() =>
                                    confirm({
                                        title: t('supplementary.confirm.deleteDataTitle'),
                                        message: t('supplementary.owner.deleteDataMessage', { name: source.participant_name }),
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
                                        message: t('supplementary.owner.removeMessage', { name: source.participant_name }),
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
            )}
        </FormModal>
    )
}
