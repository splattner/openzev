import { useTranslation } from 'react-i18next'
import { FormModal } from '../../components/FormModal'
import { formatDateTime, useAppSettings } from '../../lib/appSettings'
import { formatBytes, formatNumber } from '../../lib/numbers'
import type { BackupJob } from '../../types/api'
import { countMissingMedia, readManifest, totalRecords } from './backupHelpers'

function Row({ label, children }: { label: string; children: React.ReactNode }) {
    return (
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(7rem, 11rem) 1fr', gap: '0.75rem' }}>
            <dt className="muted" style={{ margin: 0 }}>{label}</dt>
            <dd style={{ margin: 0, wordBreak: 'break-all' }}>{children}</dd>
        </div>
    )
}

/** What a finished backup holds, read from the manifest it recorded — no archive is fetched. */
export function BackupJobDetailsModal({ job, onClose }: { job: BackupJob | null; onClose: () => void }) {
    const { t } = useTranslation()
    const { settings } = useAppSettings()

    if (!job) return null
    const manifest = readManifest(job)
    const missing = countMissingMedia(manifest)

    return (
        <FormModal isOpen title={t('pages.backups.details.title')} onClose={onClose} maxWidth="720px">
            <div className="page-stack">
                <dl className="page-stack" style={{ margin: 0 }}>
                    <Row label={t('pages.backups.details.archive')}>{job.archive_name || '—'}</Row>
                    <Row label={t('pages.backups.details.location')}>{job.archive_location || '—'}</Row>
                    <Row label={t('pages.backups.details.size')}>
                        {job.archive_bytes != null ? formatBytes(job.archive_bytes) : '—'}
                    </Row>
                    <Row label={t('pages.backups.details.checksum')}>
                        {job.archive_sha256 ? <code>{job.archive_sha256}</code> : '—'}
                    </Row>
                    <Row label={t('pages.backups.details.encryption')}>
                        {job.encrypted
                            ? t('pages.backups.details.encryptedWith', { fingerprint: job.encryption_key_fingerprint })
                            : t('pages.backups.details.notEncrypted')}
                    </Row>
                    <Row label={t('pages.backups.details.started')}>{formatDateTime(job.started_at, settings)}</Row>
                    <Row label={t('pages.backups.details.finished')}>{formatDateTime(job.completed_at, settings)}</Row>
                    {manifest && (
                        <Row label={t('pages.backups.details.records')}>{formatNumber(totalRecords(manifest))}</Row>
                    )}
                </dl>

                {job.archive_location.startsWith('s3://') && (
                    <div className="info-banner">{t('pages.backups.details.objectStorage')}</div>
                )}
                {missing > 0 && (
                    <div className="warning-banner">{t('pages.backups.details.missingPdfs', { count: missing })}</div>
                )}

                {manifest && manifest.zevs.length > 0 && (
                    <div className="table-card">
                        <table className="data-table">
                            <thead>
                                <tr>
                                    <th>{t('pages.backups.details.communities')}</th>
                                    <th>{t('pages.backups.details.records')}</th>
                                    <th>{t('pages.backups.details.invoicePdfs')}</th>
                                </tr>
                            </thead>
                            <tbody>
                                {manifest.zevs.map((zev) => (
                                    <tr key={zev.id}>
                                        <td>{zev.name}</td>
                                        <td>{formatNumber(Object.values(zev.counts).reduce((sum, n) => sum + n, 0))}</td>
                                        <td>{formatNumber(zev.media.files)} · {formatBytes(zev.media.bytes)}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}

                <div className="actions-row actions-row-end">
                    <button type="button" className="button button-secondary" onClick={onClose}>
                        {t('common.close')}
                    </button>
                </div>
            </div>
        </FormModal>
    )
}
