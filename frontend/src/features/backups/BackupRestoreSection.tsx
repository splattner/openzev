import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Switch } from '@mantine/core'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faEye, faRotateLeft } from '@fortawesome/free-solid-svg-icons'
import { useTranslation } from 'react-i18next'
import {
    createRestoreJob,
    fetchBackupDestinations,
    fetchBackupJobs,
    fetchRestoreJob,
    fetchRestoreJobs,
} from '../../lib/api/backups'
import { formatApiError } from '../../lib/api/errors'
import { queryKeys } from '../../lib/api/queryKeys'
import { formatDateTime, useAppSettings } from '../../lib/appSettings'
import { formatNumber } from '../../lib/numbers'
import { useToast } from '../../lib/toast'
import type { BackupJobStatus, RestoreJob } from '../../types/api'
import {
    canStartRestore,
    communitiesIn,
    confirmationName,
    forceableConflicts,
    hardConflicts,
    hasActiveRestore,
    readPlan,
    restorableBackups,
} from './backupHelpers'
import { RestorePlanView } from './RestorePlanView'

const POLL_MS = 3000

const STATUS_BADGE: Record<BackupJobStatus, string> = {
    queued: 'badge-neutral',
    running: 'badge-info',
    completed: 'badge-success',
    failed: 'badge-danger',
}

/**
 * Restore one community from a backup: preview first, then confirm.
 *
 * The preview is a real job (a dry run), so what is shown is exactly what the
 * backend would do, computed against the live database. Applying is a separate
 * step with its own guards — issued invoices or contracts that would be lost
 * need an explicit switch, and the community's name has to be typed — because
 * this is the one action on the page that destroys current data.
 * Restoring the whole instance is not offered here; it is a command on the server.
 */
export function BackupRestoreSection() {
    const { t } = useTranslation()
    const { settings } = useAppSettings()
    const queryClient = useQueryClient()
    const { pushToast } = useToast()

    const [backupId, setBackupId] = useState('')
    const [zevId, setZevId] = useState('')
    const [safetyId, setSafetyId] = useState('')
    const [force, setForce] = useState(false)
    const [confirmText, setConfirmText] = useState('')
    const [jobId, setJobId] = useState<string | null>(null)

    const backupsQuery = useQuery({ queryKey: queryKeys.backups.jobs(), queryFn: fetchBackupJobs })
    const destinationsQuery = useQuery({ queryKey: queryKeys.backups.destinations(), queryFn: fetchBackupDestinations })
    const historyQuery = useQuery({
        queryKey: queryKeys.backups.restores(),
        queryFn: fetchRestoreJobs,
        refetchInterval: (query) => (hasActiveRestore(query.state.data) ? POLL_MS : false),
    })
    const jobQuery = useQuery({
        queryKey: queryKeys.backups.restore(jobId ?? ''),
        queryFn: () => fetchRestoreJob(jobId as string),
        enabled: !!jobId,
        refetchInterval: (query) => (hasActiveRestore(query.state.data ? [query.state.data] : []) ? POLL_MS : false),
    })

    const backups = restorableBackups(backupsQuery.data)
    const backup = backups.find((job) => job.id === backupId) ?? backups[0]
    const communities = communitiesIn(backup)
    const selectedZev = communities.some((c) => c.id === zevId) ? zevId : (communities[0]?.id ?? '')
    const enabledDestinations = (destinationsQuery.data ?? []).filter((d) => d.enabled)
    // Default to where the backup itself lives: it is known to be reachable.
    const safetyDestination = enabledDestinations.some((d) => d.id === safetyId)
        ? safetyId
        : (enabledDestinations.find((d) => d.id === backup?.destination_id) ?? enabledDestinations[0])?.id ?? ''

    const job = jobQuery.data
    const plan = readPlan(job)
    const previewReady = !!job && job.dry_run && job.status === 'completed' && !!plan
    const confirmWith = plan ? confirmationName(plan) : ''

    // A finished restore changed data all over the app; nothing cached can be trusted.
    const finishedRestore = useRef<string | null>(null)
    useEffect(() => {
        if (job && !job.dry_run && job.status === 'completed' && finishedRestore.current !== job.id) {
            finishedRestore.current = job.id
            void queryClient.invalidateQueries()
        }
    }, [job, queryClient])

    function reset(next: { backupId?: string; zevId?: string }) {
        if (next.backupId !== undefined) setBackupId(next.backupId)
        if (next.zevId !== undefined) setZevId(next.zevId)
        setJobId(null)
        setForce(false)
        setConfirmText('')
    }

    const start = useMutation({
        mutationFn: (dryRun: boolean) =>
            createRestoreJob({
                source_backup_id: backup!.id,
                target_zev_id: selectedZev,
                dry_run: dryRun,
                ...(dryRun ? {} : { force }),
                ...(!dryRun && plan?.zev.exists_now && safetyDestination ? { safety_destination_id: safetyDestination } : {}),
            }),
        onSuccess: (created) => {
            setJobId(created.id)
            void queryClient.invalidateQueries({ queryKey: queryKeys.backups.restores() })
        },
        onError: (error) => pushToast(formatApiError(error), 'error'),
    })

    const running = job?.status === 'queued' || job?.status === 'running'
    const canPreview = !!backup && !!selectedZev && !start.isPending && !running
    const canApply =
        previewReady &&
        !!plan &&
        canStartRestore(plan, force) &&
        confirmText.trim() === confirmWith &&
        (!plan.zev.exists_now || !!safetyDestination) &&
        !start.isPending &&
        !running

    return (
        <section className="card page-stack">
            <div>
                <h3 style={{ margin: 0 }}>{t('pages.backups.restore.title')}</h3>
                <p className="muted" style={{ margin: '0.25rem 0 0' }}>
                    {t('pages.backups.restore.description', {
                        command: 'python manage.py openzev_restore --mode instance',
                    })}
                </p>
            </div>

            {backupsQuery.isLoading ? (
                <div className="muted">{t('common.loading')}</div>
            ) : backups.length === 0 ? (
                <div className="muted">{t('pages.backups.restore.noBackups')}</div>
            ) : (
                <form
                    className="page-stack"
                    onSubmit={(event) => {
                        event.preventDefault()
                        if (canPreview) start.mutate(true)
                    }}
                >
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '1rem' }}>
                        <label>
                            <span>{t('pages.backups.restore.backup')}</span>
                            <select value={backup?.id ?? ''} onChange={(event) => reset({ backupId: event.target.value, zevId: '' })}>
                                {backups.map((candidate) => (
                                    <option key={candidate.id} value={candidate.id}>
                                        {t('pages.backups.restore.backupOption', {
                                            date: formatDateTime(candidate.completed_at, settings),
                                            scope:
                                                candidate.scope === 'zev'
                                                    ? t('pages.backups.jobs.scopeZev')
                                                    : t('pages.backups.jobs.scopeInstance'),
                                            destination: candidate.destination_name || '—',
                                        })}
                                    </option>
                                ))}
                            </select>
                        </label>
                        <label>
                            <span>{t('pages.backups.restore.community')}</span>
                            <select value={selectedZev} onChange={(event) => reset({ zevId: event.target.value })}>
                                {communities.map((community) => (
                                    <option key={community.id} value={community.id}>{community.name}</option>
                                ))}
                            </select>
                        </label>
                    </div>

                    <div className="actions-row">
                        <button type="submit" className="button button-secondary" disabled={!canPreview}>
                            <FontAwesomeIcon icon={faEye} fixedWidth />
                            {t('pages.backups.restore.preview')}
                        </button>
                    </div>
                </form>
            )}

            {running && (
                <div className="info-banner">
                    {job?.dry_run ? t('pages.backups.restore.previewRunning') : t('pages.backups.restore.restoreRunning')}
                </div>
            )}

            {job?.status === 'failed' && (
                <div className="error-banner">
                    <strong>{t('pages.backups.restore.failed')}</strong>
                    <div>{job.error_message}</div>
                    {'verification_failures' in job.plan_json && (job.plan_json.verification_failures ?? []).length > 0 && (
                        <ul style={{ margin: '0.5rem 0 0', paddingLeft: '1.25rem' }}>
                            {(job.plan_json.verification_failures ?? []).map((failure) => (
                                <li key={failure} style={{ overflowWrap: 'anywhere' }}>{failure}</li>
                            ))}
                        </ul>
                    )}
                </div>
            )}

            {plan && job && job.status !== 'queued' && job.status !== 'running' && (
                <div className="page-stack">
                    <h4 style={{ margin: 0 }}>
                        {job.dry_run ? t('pages.backups.restore.previewTitle', { name: plan.zev.name }) : t('pages.backups.restore.restoredTitle', { name: plan.zev.name })}
                    </h4>
                    {!job.dry_run && job.status === 'completed' && (
                        <div className="success-banner">
                            {t('pages.backups.restore.done', {
                                count: formatNumber(Object.values(plan.restored ?? {}).reduce((sum, n) => sum + n, 0)),
                            })}
                            {plan.safety_backup_id && <div>{t('pages.backups.restore.safetyTaken')}</div>}
                        </div>
                    )}
                    <RestorePlanView plan={plan} />
                </div>
            )}

            {previewReady && plan && (
                <div className="page-stack" style={{ borderTop: '1px solid var(--border-default)', paddingTop: '1rem' }}>
                    {hardConflicts(plan).length > 0 ? (
                        <div className="error-banner">{t('pages.backups.restore.blocked')}</div>
                    ) : (
                        <>
                            <div className="warning-banner">
                                {plan.zev.exists_now
                                    ? t('pages.backups.restore.warning', { name: plan.zev.current_name })
                                    : t('pages.backups.restore.warningNew', { name: plan.zev.name })}
                            </div>

                            {forceableConflicts(plan).length > 0 && (
                                <Switch
                                    checked={force}
                                    onChange={(event) => setForce(event.currentTarget.checked)}
                                    label={t('pages.backups.restore.force')}
                                />
                            )}

                            {plan.zev.exists_now && (
                                <label>
                                    <span>{t('pages.backups.restore.safetyDestination')}</span>
                                    <select value={safetyDestination} onChange={(event) => setSafetyId(event.target.value)}>
                                        {enabledDestinations.length === 0 && (
                                            <option value="">{t('pages.backups.jobs.noDestination')}</option>
                                        )}
                                        {enabledDestinations.map((destination) => (
                                            <option key={destination.id} value={destination.id}>{destination.name}</option>
                                        ))}
                                    </select>
                                    <span className="muted">{t('pages.backups.restore.safetyHint')}</span>
                                </label>
                            )}

                            <label>
                                <span>{t('pages.backups.restore.confirm', { name: confirmWith })}</span>
                                <input
                                    value={confirmText}
                                    onChange={(event) => setConfirmText(event.target.value)}
                                    autoComplete="off"
                                    aria-label={t('pages.backups.restore.confirmLabel')}
                                />
                            </label>

                            <div className="actions-row">
                                <button
                                    type="button"
                                    className="button button-danger"
                                    disabled={!canApply}
                                    onClick={() => start.mutate(false)}
                                >
                                    <FontAwesomeIcon icon={faRotateLeft} fixedWidth />
                                    {t('pages.backups.restore.apply')}
                                </button>
                            </div>
                        </>
                    )}
                </div>
            )}

            <RestoreHistory jobs={historyQuery.data ?? []} loading={historyQuery.isLoading} />
        </section>
    )
}

function RestoreHistory({ jobs, loading }: { jobs: RestoreJob[]; loading: boolean }) {
    const { t } = useTranslation()
    const { settings } = useAppSettings()
    if (loading || jobs.length === 0) return null

    return (
        <div className="page-stack">
            <h4 style={{ margin: 0 }}>{t('pages.backups.restore.history')}</h4>
            <div className="table-card">
                <table className="data-table">
                    <thead>
                        <tr>
                            <th>{t('pages.backups.restore.columns.when')}</th>
                            <th>{t('pages.backups.restore.community')}</th>
                            <th>{t('pages.backups.restore.columns.backup')}</th>
                            <th>{t('pages.backups.restore.columns.kind')}</th>
                            <th>{t('pages.backups.jobs.columns.status')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {jobs.map((row) => (
                            <tr key={row.id}>
                                <td>{formatDateTime(row.started_at ?? row.created_at, settings)}</td>
                                <td>{row.target_zev_name || row.target_zev_id}</td>
                                <td>{row.source_created_at ? formatDateTime(row.source_created_at, settings) : row.source_description || '—'}</td>
                                <td>
                                    {row.dry_run ? t('pages.backups.restore.kindPreview') : t('pages.backups.restore.kindRestore')}
                                    {row.force && <span className="badge badge-warning" style={{ marginLeft: '0.4rem' }}>{t('pages.backups.restore.forced')}</span>}
                                </td>
                                <td>
                                    <span className={`badge ${STATUS_BADGE[row.status]}`}>{t(`pages.backups.jobs.status.${row.status}`)}</span>
                                    {row.status === 'failed' && row.error_message && (
                                        <div className="muted" style={{ marginTop: '0.25rem', maxWidth: '28rem' }}>{row.error_message}</div>
                                    )}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    )
}
