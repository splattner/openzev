import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { formatDateTime } from '../../lib/appSettings'
import type { AppSettings, DynamicTariffSource } from '../../types/api'
import { Disclosure } from '../../components/Disclosure'

/**
 * Shared-source facts beside the linked tariff: which source and whether it is
 * delivering, up front; where it is fetched from and what it covers, on
 * demand. Maintenance stays in the platform hub, which only an admin can open.
 */
export function DynamicSourceSummary({ source, settings, canOperate }: {
    source: DynamicTariffSource
    settings: AppSettings
    canOperate: boolean
}) {
    const { t } = useTranslation()
    return (
        <div className="tariff-source-summary">
            <div className="actions-row actions-row-wrap">
                <strong>{source.label}</strong>
                {!source.enabled && <span className="badge badge-neutral">{t('pages.dynamicSources.status.disabled')}</span>}
                <span className={`badge ${source.last_fetch_status === 'failed' ? 'badge-danger' : source.last_fetch_status === 'ok' ? 'badge-success' : 'badge-neutral'}`}>
                    {t(`pages.dynamicSources.status.${source.last_fetch_status}`)}
                </span>
                {canOperate && (
                    <Link to={`/admin/dynamic-sources?source=${encodeURIComponent(source.id)}`}>{t('pages.dynamicSources.manageSource')}</Link>
                )}
            </div>
            {source.last_success_at && (
                <p className="muted" style={{ margin: 0 }}>{t('pages.dynamicSources.lastSuccess', { time: formatDateTime(source.last_success_at, settings) })}</p>
            )}
            {source.last_fetch_status === 'failed' && source.last_fetch_error && <p className="text-error" style={{ margin: 0 }}>{source.last_fetch_error}</p>}
            <Disclosure lazy summary={t('pages.dynamicSources.sourceDetails')}>
                <div className="tariff-source-summary">
                    <p className="muted" style={{ margin: 0, overflowWrap: 'anywhere' }}>{source.url}</p>
                    <p className="muted" style={{ margin: 0 }}>
                        {t(`pages.dynamicSources.versions.${source.api_version}`)}
                        {' · '}{t(`pages.dynamicSources.types.${source.tariff_type}`)}
                        {source.tariff_name ? ` · ${source.tariff_name}` : ''}
                    </p>
                    <p className="muted" style={{ margin: 0 }}>
                        {source.point_count > 0 ? t('pages.dynamicSources.history.coverage', {
                            from: formatDateTime(source.covers_from, settings),
                            to: formatDateTime(source.covers_to, settings),
                            count: source.point_count,
                        }) : t('pages.dynamicSources.noCoverage')}
                        {source.point_count > 0 && <>{' · '}{t('pages.dynamicSources.coverageHint')}</>}
                    </p>
                    <p className="muted" style={{ margin: 0 }}>
                        {t('pages.dynamicSources.globalReuseSummary', { tariffs: source.linked_tariff_count, zevs: source.linked_zev_count })}
                    </p>
                </div>
            </Disclosure>
        </div>
    )
}
