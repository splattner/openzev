import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { StatCard } from '../../components/StatCard'
import { fetchBackupStatus } from '../../lib/api/backups'
import { queryKeys } from '../../lib/api/queryKeys'
import { formatDateTime, useAppSettings } from '../../lib/appSettings'
import { BackupDestinationsSection } from './BackupDestinationsSection'
import { BackupJobsSection } from './BackupJobsSection'
import { BackupScheduleSection } from './BackupScheduleSection'
import { BackupRestoreSection } from './BackupRestoreSection'

/** The `backup` tab of System Settings: is it safe, where does it go, what has run. */
export function BackupSettingsSection() {
    const { t } = useTranslation()
    const { settings } = useAppSettings()
    const statusQuery = useQuery({ queryKey: queryKeys.backups.status(), queryFn: fetchBackupStatus })
    const status = statusQuery.data

    return (
        <div className="page-stack">
            <section className="card page-stack">
                <p className="muted" style={{ margin: 0 }}>{t('pages.backups.intro')}</p>

                {/* Encryption is optional (ADR 0024), so the unencrypted state has to
                    be loud: an archive holds password hashes, personal data and the
                    OAuth client secret in the clear. */}
                {status?.encryption_key_problem ? (
                    <div className="error-banner">
                        {t('pages.backups.status.keyProblem', { problem: status.encryption_key_problem })}
                    </div>
                ) : status && !status.encrypted ? (
                    <div className="warning-banner">
                        <strong>{t('pages.backups.status.unencryptedTitle')}</strong>
                        <div>{t('pages.backups.status.unencrypted')}</div>
                    </div>
                ) : status ? (
                    <div className="info-banner">
                        {t('pages.backups.status.encrypted', { fingerprint: status.encryption_key_fingerprint })}
                    </div>
                ) : null}

                {status?.stale && (
                    <div className="error-banner">
                        <strong>{t('pages.backups.status.staleTitle')}</strong>
                        <div>
                            {status.age_hours == null
                                ? t('pages.backups.status.staleNever')
                                : t('pages.backups.status.stale', {
                                      hours: Math.round(status.age_hours),
                                      interval: status.schedule_interval_hours ?? 0,
                                  })}
                        </div>
                    </div>
                )}

                <p className="muted" style={{ margin: 0 }}>
                    {t('pages.backups.restoreNotice', {
                        restoreCommand: 'python manage.py openzev_restore --mode instance --from <archive>',
                        command: 'python manage.py openzev_backup_verify',
                    })}
                </p>
            </section>

            <section
                style={{
                    display: 'grid',
                    gap: '1rem',
                    gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
                }}
            >
                <StatCard
                    label={t('pages.backups.status.lastSuccess')}
                    value={
                        status?.last_successful
                            ? formatDateTime(status.last_successful.completed_at, settings)
                            : t('pages.backups.status.never')
                    }
                    hint={status?.last_successful?.destination_name || undefined}
                    tone={status?.last_successful ? 'success' : 'warning'}
                />
                {status?.last_failed && (
                    <StatCard
                        label={t('pages.backups.status.lastFailed')}
                        value={formatDateTime(status.last_failed.completed_at ?? status.last_failed.created_at, settings)}
                        hint={status.last_failed.error_message || undefined}
                        tone="danger"
                    />
                )}
                <StatCard label={t('pages.backups.status.enabledDestinations')} value={status?.destinations_enabled ?? 0} />
            </section>

            <BackupDestinationsSection status={status} />
            <BackupScheduleSection status={status} />
            <BackupJobsSection />
            <BackupRestoreSection />
        </div>
    )
}
