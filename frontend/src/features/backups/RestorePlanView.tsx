import { useTranslation } from 'react-i18next'
import { formatDateTime, useAppSettings } from '../../lib/appSettings'
import { formatNumber } from '../../lib/numbers'
import type { RestorePlan } from '../../types/api'
import { RESTORE_SECTION_ORDER } from './backupHelpers'

/**
 * What a restore would do to one community, as the backend planned it: which
 * tables are replaced, which accounts are relinked, and what stands in the way.
 * The same view shows a preview, a refusal and the plan a finished restore used.
 */
export function RestorePlanView({ plan }: { plan: RestorePlan }) {
    const { t } = useTranslation()
    const { settings } = useAppSettings()
    const rows = RESTORE_SECTION_ORDER.filter((name) => plan.sections[name])

    return (
        <div className="page-stack">
            {!plan.zev.exists_now && (
                <div className="info-banner">{t('pages.backups.restore.plan.recreated', { name: plan.zev.name })}</div>
            )}

            <div className="muted">
                {t('pages.backups.restore.plan.backupTaken', { date: formatDateTime(plan.backup.created_at, settings) })}
                {plan.backup.openzev_version && (
                    <> · {t('pages.backups.restore.plan.version', { version: plan.backup.openzev_version })}</>
                )}
            </div>

            <div className="table-card">
                <table className="data-table">
                    <thead>
                        <tr>
                            <th>{t('pages.backups.restore.plan.section')}</th>
                            <th style={{ textAlign: 'right' }}>{t('pages.backups.restore.plan.inBackup')}</th>
                            <th style={{ textAlign: 'right' }}>{t('pages.backups.restore.plan.now')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows.map((name) => {
                            const section = plan.sections[name]
                            return (
                                <tr key={name}>
                                    <td>
                                        {t(`pages.backups.restore.sections.${name}`)}
                                        {section.kept && (
                                            <span className="muted"> — {t('pages.backups.restore.plan.kept')}</span>
                                        )}
                                    </td>
                                    <td style={{ textAlign: 'right' }}>{formatNumber(section.backup)}</td>
                                    <td style={{ textAlign: 'right' }}>{formatNumber(section.current)}</td>
                                </tr>
                            )
                        })}
                    </tbody>
                </table>
            </div>

            <div>
                {t('pages.backups.restore.plan.accounts', { count: plan.accounts.relink })}
                {plan.media.files > 0 && <> · {t('pages.backups.restore.plan.pdfs', { count: plan.media.files })}</>}
            </div>

            {plan.accounts.missing.length > 0 && (
                <div className="warning-banner">
                    <strong>{t('pages.backups.restore.plan.missingAccountsTitle')}</strong>
                    <div>{t('pages.backups.restore.plan.missingAccounts', { accounts: plan.accounts.missing.join(', ') })}</div>
                </div>
            )}
            {plan.media.missing > 0 && (
                <div className="warning-banner">{t('pages.backups.restore.plan.missingPdfs', { count: plan.media.missing })}</div>
            )}

            {plan.conflicts.length > 0 && (
                <div className="page-stack" style={{ gap: '0.5rem' }}>
                    <strong>{t('pages.backups.restore.plan.conflictsTitle')}</strong>
                    {plan.conflicts.map((conflict, index) => (
                        <div key={`${conflict.kind}-${index}`} className={conflict.overridable ? 'warning-banner' : 'error-banner'}>
                            <div>
                                <span className={`badge ${conflict.overridable ? 'badge-warning' : 'badge-danger'}`}>
                                    {conflict.overridable
                                        ? t('pages.backups.restore.plan.needsForce')
                                        : t('pages.backups.restore.plan.cannotOverride')}
                                </span>{' '}
                                {t(`pages.backups.restore.conflict.${conflict.kind}`)}
                            </div>
                            <div style={{ overflowWrap: 'anywhere' }}>{conflict.detail}</div>
                        </div>
                    ))}
                </div>
            )}
        </div>
    )
}
