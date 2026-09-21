import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faCircleInfo, faDownload, faPlay, faShieldHalved, faTrash } from '@fortawesome/free-solid-svg-icons'
import { useTranslation } from 'react-i18next'
import {
    createBackupJob,
    deleteBackupArtifact,
    downloadBackupArtifact,
    fetchBackupDestinations,
    fetchBackupJobs,
    verifyBackupJob,
} from '../../lib/api/backups'
import { formatApiError } from '../../lib/api/errors'
import { queryKeys } from '../../lib/api/queryKeys'
import { fetchZevs } from '../../lib/api/zev'
import { formatDateTime, useAppSettings } from '../../lib/appSettings'
import { downloadBlob } from '../../lib/downloadBlob'
import { formatBytes } from '../../lib/numbers'
import { useToast } from '../../lib/toast'
import { ConfirmDialog, useConfirmDialog } from '../../components/ConfirmDialog'
import type { BackupJob, BackupJobScope, BackupJobStatus } from '../../types/api'
import { BackupJobDetailsModal } from './BackupJobDetailsModal'
import { fileGone, hasActiveJob, hasFile, isDownloadable, verificationState } from './backupHelpers'

const POLL_MS = 3000

const STATUS_BADGE: Record<BackupJobStatus, string> = {
    queued: 'badge-neutral',
    running: 'badge-info',
    completed: 'badge-success',
    failed: 'badge-danger',
}

export function BackupJobsSection() {
    const { t } = useTranslation()
    const { settings } = useAppSettings()
    const queryClient = useQueryClient()
    const { pushToast } = useToast()
    const { dialog, confirm, handleConfirm, handleCancel, isLoading: dialogLoading } = useConfirmDialog()

    const [scope, setScope] = useState<BackupJobScope>('instance')
    const [zevId, setZevId] = useState('')
    const [destinationId, setDestinationId] = useState('')
    const [detailJob, setDetailJob] = useState<BackupJob | null>(null)

    const destinationsQuery = useQuery({
        queryKey: queryKeys.backups.destinations(),
        queryFn: fetchBackupDestinations,
    })
    const zevsQuery = useQuery({ queryKey: queryKeys.zev.list(), queryFn: fetchZevs })
    const jobsQuery = useQuery({
        queryKey: queryKeys.backups.jobs(),
        queryFn: fetchBackupJobs,
        // Poll only while something is in flight, so an idle tab makes no requests.
        refetchInterval: (query) => (hasActiveJob(query.state.data) ? POLL_MS : false),
    })

    const enabledDestinations = (destinationsQuery.data ?? []).filter((destination) => destination.enabled)
    const zevs = zevsQuery.data ?? []
    const jobs = jobsQuery.data ?? []

    // The status card (last backup, encryption) reads different data than the
    // list, so refresh it once running work has finished.
    const wasActive = useRef(false)
    const active = hasActiveJob(jobsQuery.data)
    useEffect(() => {
        if (wasActive.current && !active) {
            void queryClient.invalidateQueries({ queryKey: queryKeys.backups.status() })
        }
        wasActive.current = active
    }, [active, queryClient])

    // Default to the first enabled destination, and recover if the chosen one is
    // deleted or disabled underneath the form.
    const selectedDestination = enabledDestinations.some((d) => d.id === destinationId)
        ? destinationId
        : (enabledDestinations[0]?.id ?? '')

    const startMutation = useMutation({
        mutationFn: () =>
            createBackupJob({
                scope,
                destination_id: selectedDestination,
                ...(scope === 'zev' ? { zev_id: zevId } : {}),
            }),
        onSuccess: () => {
            void queryClient.invalidateQueries({ queryKey: queryKeys.backups.jobs() })
            pushToast(t('pages.backups.jobs.queued'), 'success')
        },
        onError: (error) => pushToast(formatApiError(error), 'error'),
    })

    const verifyMutation = useMutation({
        mutationFn: (job: BackupJob) => verifyBackupJob(job.id),
        onSuccess: () => {
            void queryClient.invalidateQueries({ queryKey: queryKeys.backups.jobs() })
            pushToast(t('pages.backups.jobs.checkQueued'), 'success')
        },
        onError: (error) => pushToast(formatApiError(error), 'error'),
    })

    const deleteFileMutation = useMutation({
        mutationFn: (job: BackupJob) => deleteBackupArtifact(job.id),
        onSuccess: () => {
            void queryClient.invalidateQueries({ queryKey: queryKeys.backups.jobs() })
            pushToast(t('pages.backups.jobs.fileDeleted'), 'success')
        },
        onError: (error) => pushToast(formatApiError(error), 'error'),
    })

    const askToDeleteFile = (job: BackupJob) =>
        confirm({
            title: t('pages.backups.jobs.deleteFileTitle'),
            message: t('pages.backups.jobs.deleteFileMessage', { name: job.archive_name }),
            confirmText: t('pages.backups.jobs.deleteFile'),
            isDangerous: true,
            onConfirm: () => deleteFileMutation.mutateAsync(job),
        })

    const downloadMutation = useMutation({
        mutationFn: async (job: BackupJob) => downloadBlob(await downloadBackupArtifact(job.id), job.archive_name),
        onError: () => pushToast(t('pages.backups.jobs.downloadFailed'), 'error'),
    })

    const canStart =
        !!selectedDestination && (scope === 'instance' || !!zevId) && !startMutation.isPending

    return (
        <section className="card page-stack">
            <div>
                <h3 style={{ margin: 0 }}>{t('pages.backups.jobs.title')}</h3>
                <p className="muted" style={{ margin: '0.25rem 0 0' }}>
                    {t('pages.backups.jobs.description', { command: 'python manage.py openzev_backup' })}
                </p>
            </div>

            <form
                className="page-stack"
                onSubmit={(event) => {
                    event.preventDefault()
                    if (canStart) startMutation.mutate()
                }}
            >
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1rem' }}>
                    <label>
                        <span>{t('pages.backups.jobs.scope')}</span>
                        <select value={scope} onChange={(event) => setScope(event.target.value as BackupJobScope)}>
                            <option value="instance">{t('pages.backups.jobs.scopeInstance')}</option>
                            <option value="zev">{t('pages.backups.jobs.scopeZev')}</option>
                        </select>
                    </label>

                    {scope === 'zev' && (
                        <label>
                            <span>{t('pages.backups.jobs.zev')}</span>
                            <select value={zevId} onChange={(event) => setZevId(event.target.value)}>
                                <option value="">{t('pages.backups.jobs.selectZev')}</option>
                                {zevs.map((zev) => (
                                    <option key={zev.id} value={zev.id}>{zev.name}</option>
                                ))}
                            </select>
                        </label>
                    )}

                    <label>
                        <span>{t('pages.backups.jobs.destination')}</span>
                        <select
                            value={selectedDestination}
                            onChange={(event) => setDestinationId(event.target.value)}
                            disabled={enabledDestinations.length === 0}
                        >
                            {enabledDestinations.length === 0 && (
                                <option value="">{t('pages.backups.jobs.noDestination')}</option>
                            )}
                            {enabledDestinations.map((destination) => (
                                <option key={destination.id} value={destination.id}>{destination.name}</option>
                            ))}
                        </select>
                    </label>
                </div>

                <div className="actions-row">
                    <button type="submit" className="button button-primary" disabled={!canStart}>
                        <FontAwesomeIcon icon={faPlay} fixedWidth />
                        {t('pages.backups.jobs.backUpNow')}
                    </button>
                </div>
            </form>

            {jobsQuery.isLoading ? (
                <div className="muted">{t('common.loading')}</div>
            ) : jobs.length === 0 ? (
                <div className="muted">{t('pages.backups.jobs.empty')}</div>
            ) : (
                <div className="table-card">
                    <table className="data-table">
                        <thead>
                            <tr>
                                <th>{t('pages.backups.jobs.columns.created')}</th>
                                <th>{t('pages.backups.jobs.columns.scope')}</th>
                                <th>{t('pages.backups.jobs.columns.destination')}</th>
                                <th>{t('pages.backups.jobs.columns.status')}</th>
                                <th>{t('pages.backups.jobs.columns.size')}</th>
                                <th>{t('pages.backups.jobs.columns.encryption')}</th>
                                <th>{t('pages.backups.jobs.columns.integrity')}</th>
                                <th>{t('common.actions')}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {jobs.map((job) => (
                                <tr key={job.id}>
                                    <td>{formatDateTime(job.started_at ?? job.created_at, settings)}</td>
                                    <td>
                                        {job.scope === 'zev'
                                            ? job.zev_name || t('pages.backups.jobs.scopeZev')
                                            : t('pages.backups.jobs.scopeInstance')}
                                        {job.trigger !== 'manual' && (
                                            <span className="badge badge-neutral" style={{ marginLeft: '0.4rem' }}>
                                                {t(`pages.backups.jobs.trigger.${job.trigger}`)}
                                            </span>
                                        )}
                                    </td>
                                    <td>{job.destination_name || '—'}</td>
                                    <td>
                                        <span className={`badge ${STATUS_BADGE[job.status]}`}>
                                            {t(`pages.backups.jobs.status.${job.status}`)}
                                        </span>
                                        {fileGone(job) && (
                                            <div className="muted" style={{ marginTop: '0.25rem' }}>
                                                {t(`pages.backups.jobs.fileGone.${job.artifact_deleted_reason || 'manual'}`)}
                                            </div>
                                        )}
                                        {hasFile(job) && job.file_expires_at && (
                                            <div className="muted" style={{ marginTop: '0.25rem' }}>
                                                {t('pages.backups.jobs.expires', { date: formatDateTime(job.file_expires_at, settings) })}
                                            </div>
                                        )}
                                        {job.status === 'failed' && job.error_message && (
                                            <div className="muted" style={{ marginTop: '0.25rem', maxWidth: '28rem' }}>
                                                {job.error_message}
                                            </div>
                                        )}
                                    </td>
                                    <td>{job.archive_bytes != null ? formatBytes(job.archive_bytes) : '—'}</td>
                                    <td>
                                        {job.status === 'completed' ? (
                                            <span className={`badge ${job.encrypted ? 'badge-success' : 'badge-warning'}`}>
                                                {job.encrypted
                                                    ? t('pages.backups.jobs.encrypted')
                                                    : t('pages.backups.jobs.notEncrypted')}
                                            </span>
                                        ) : (
                                            '—'
                                        )}
                                    </td>
                                    <td>
                                        {job.status !== 'completed' || fileGone(job) ? (
                                            '—'
                                        ) : (
                                            <VerificationBadge job={job} />
                                        )}
                                    </td>
                                    <td className="actions-cell">
                                        <div className="actions-cell-content">
                                            {job.status === 'completed' && (
                                                <button
                                                    type="button"
                                                    className="button button-secondary button-compact"
                                                    onClick={() => setDetailJob(job)}
                                                >
                                                    <FontAwesomeIcon icon={faCircleInfo} fixedWidth />
                                                    {t('pages.backups.jobs.details')}
                                                </button>
                                            )}
                                            {hasFile(job) && (
                                                <button
                                                    type="button"
                                                    className="button button-secondary button-compact"
                                                    disabled={job.verifying || verifyMutation.isPending}
                                                    onClick={() => verifyMutation.mutate(job)}
                                                >
                                                    <FontAwesomeIcon icon={faShieldHalved} fixedWidth />
                                                    {t('pages.backups.jobs.check')}
                                                </button>
                                            )}
                                            {isDownloadable(job) && (
                                                <button
                                                    type="button"
                                                    className="button button-secondary button-compact"
                                                    disabled={downloadMutation.isPending}
                                                    onClick={() => downloadMutation.mutate(job)}
                                                >
                                                    <FontAwesomeIcon icon={faDownload} fixedWidth />
                                                    {t('pages.backups.jobs.download')}
                                                </button>
                                            )}
                                            {hasFile(job) && (
                                                <button
                                                    type="button"
                                                    className="button button-secondary button-compact"
                                                    onClick={() => askToDeleteFile(job)}
                                                >
                                                    <FontAwesomeIcon icon={faTrash} fixedWidth />
                                                    {t('pages.backups.jobs.deleteFile')}
                                                </button>
                                            )}
                                        </div>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}

            <BackupJobDetailsModal job={detailJob} onClose={() => setDetailJob(null)} />

            {dialog && (
                <ConfirmDialog
                    title={dialog.title}
                    message={dialog.message}
                    confirmText={dialog.confirmText}
                    isDangerous={dialog.isDangerous}
                    isLoading={dialogLoading}
                    onConfirm={handleConfirm}
                    onCancel={handleCancel}
                />
            )}
        </section>
    )
}

/** The result of the last check of a backup's stored file. A failure names why. */
function VerificationBadge({ job }: { job: BackupJob }) {
    const { t } = useTranslation()
    const { settings } = useAppSettings()
    const state = verificationState(job)

    if (state === 'checking') return <span className="badge badge-info">{t('pages.backups.jobs.verification.checking')}</span>
    if (state === 'never') return <span className="badge badge-neutral">{t('pages.backups.jobs.verification.never')}</span>
    return (
        <>
            <span className={`badge ${state === 'ok' ? 'badge-success' : 'badge-danger'}`}>
                {t(`pages.backups.jobs.verification.${state}`)}
            </span>
            <div className="muted" style={{ marginTop: '0.25rem', maxWidth: '20rem', overflowWrap: 'anywhere' }}>
                {job.verified_at ? formatDateTime(job.verified_at, settings) : ''}
                {state === 'failed' && job.verification_message && <div>{job.verification_message}</div>}
            </div>
        </>
    )
}
