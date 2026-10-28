import { useMemo, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { DataTable, type ColumnDef } from '../../components/DataTable'
import { Disclosure } from '../../components/Disclosure'
import { FormModal } from '../../components/FormModal'
import { HeldReadingsPanel } from '../../components/HeldReadingsPanel'
import { formatDateTime, useAppSettings } from '../../lib/appSettings'
import type { ImportLog, SdatIssue } from '../../types/api'
import {
    SDAT_COUNT_ORDER,
    importLogProtectionCode,
    isSdatLog,
    sdatIssueParams,
    sdatOutcomeKind,
    type SdatOutcomeKind,
} from './sdatOutcome'

function DetailRow({ label, children }: { label: string; children: ReactNode }) {
    return <div><strong>{label}</strong> {children}</div>
}

const OUTCOME_BADGE: Record<SdatOutcomeKind, string> = {
    accepted: 'badge badge-success',
    correctionOnly: 'badge badge-success',
    held: 'badge badge-warning',
    unchanged: 'badge badge-neutral',
    rejected: 'badge badge-danger',
    legacy: 'badge badge-neutral',
}

function SdatIssues({ issues }: { issues: SdatIssue[] }) {
    const { t } = useTranslation()
    const ordered = useMemo(
        () => [...issues].sort((left, right) => (left.severity === right.severity ? 0 : left.severity === 'error' ? -1 : 1)),
        [issues],
    )
    if (ordered.length === 0) return null
    return (
        <div className="page-stack" style={{ gap: '0.5rem' }}>
            <h4 style={{ marginBottom: '0.2rem' }}>{t('pages.imports.protocol.issues')}</h4>
            {ordered.map((issue, index) => (
                <SdatIssueRow key={`${issue.code}-${index}`} issue={issue} />
            ))}
        </div>
    )
}

function SdatIssueRow({ issue }: { issue: SdatIssue }) {
    const { t } = useTranslation()
    const params = sdatIssueParams(issue)
    return (
        <div className="card" style={{ padding: '0.6rem 0.8rem' }}>
            <div className="actions-row actions-row-wrap">
                <span className={`badge ${issue.severity === 'error' ? 'badge-danger' : 'badge-info'}`}>
                    {issue.severity === 'error'
                        ? t('pages.imports.protocol.issueError')
                        : t('pages.imports.protocol.issueInfo')}
                </span>
                <strong>{t(`pages.imports.issues.${issue.code}`, { defaultValue: t('pages.imports.issues.unknownCode', { code: issue.code }) })}</strong>
            </div>
            {params.length > 0 && (
                <dl className="muted" style={{ margin: '0.4rem 0 0', fontSize: '0.85rem', display: 'grid', gap: '0.15rem' }}>
                    {params.map(({ key, value }) => (
                        <div key={key} style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
                            <dt style={{ fontWeight: 600 }}>{t(`pages.imports.protocol.issueParam.${key}`)}:</dt>
                            <dd style={{ margin: 0, overflowWrap: 'anywhere' }}>
                                {key === 'direction' ? t(`pages.imports.preview.${value === 'out' ? 'directionOut' : 'directionIn'}`) : value}
                            </dd>
                        </div>
                    ))}
                </dl>
            )}
            <Disclosure className="muted disclosure-sm mt-05" summary={t('pages.imports.protocol.technicalDetails')}>
                <p style={{ margin: '0.4rem 0 0' }}>{issue.message}</p>
            </Disclosure>
        </div>
    )
}

export function ImportProtocolModal({ log, onClose }: { log: ImportLog | null; onClose: () => void }) {
    const { t } = useTranslation()
    const { settings } = useAppSettings()

    function timestampTimezoneLabel(zone: ImportLog['timestamp_timezone']) {
        if (zone === 'Europe/Zurich') return t('pages.imports.wizard.timestampTimezoneZurich')
        if (zone === 'UTC') return t('pages.imports.wizard.timestampTimezoneUtc')
        return t('pages.imports.protocol.timestampTimezoneLegacy')
    }

    const columns = useMemo<ColumnDef<NonNullable<ImportLog['errors']>[number], unknown>[]>(
        () => [
            {
                accessorKey: 'row',
                header: t('pages.imports.protocol.row'),
                cell: (ctx) => ctx.row.original.row ?? t('pages.imports.protocol.general'),
            },
            {
                accessorKey: 'meter_id',
                header: t('pages.imports.protocol.meter'),
                cell: (ctx) => ctx.row.original.meter_id ?? '-',
            },
            {
                accessorKey: 'error',
                header: t('pages.imports.protocol.reason'),
            },
        ],
        [t],
    )

    const structured = !!log && isSdatLog(log)
    const outcome: SdatOutcomeKind = log ? sdatOutcomeKind(log) : 'legacy'
    const protection = log ? importLogProtectionCode(log) : null
    const counts = log?.result_counts
    const nonzeroCounts = structured && counts
        ? SDAT_COUNT_ORDER.filter((key) => (counts[key] ?? 0) !== 0)
        : []
    const delivery = log?.source_delivery
    const hasDelivery = !!delivery && !!delivery.delivery_id

    return (
        <FormModal isOpen={!!log} title={t('pages.imports.protocol.title')} onClose={onClose}>
            {log && (
                <div className="page-stack" style={{ gap: '0.75rem', overflowWrap: 'anywhere' }}>
                    <DetailRow label={t('pages.imports.protocol.created')}>{formatDateTime(log.created_at, settings)}</DetailRow>
                    <DetailRow label={t('pages.imports.protocol.source')}>{log.source}</DetailRow>
                    <DetailRow label={t('pages.imports.protocol.zev')}>{log.zev_name || log.zev || '-'}</DetailRow>
                    <DetailRow label={t('pages.imports.protocol.importedBy')}>{log.imported_by_display || '-'}</DetailRow>
                    <DetailRow label={t('pages.imports.protocol.batchId')}>{log.batch_id || '-'}</DetailRow>
                    {log.source === 'csv' && (
                        <DetailRow label={t('pages.imports.protocol.timestampTimezone')}>{timestampTimezoneLabel(log.timestamp_timezone)}</DetailRow>
                    )}
                    <DetailRow label={t('pages.imports.protocol.filename')}>{log.filename || '-'}</DetailRow>

                    {structured ? (
                        <>
                            <div className="actions-row actions-row-wrap">
                                <span className={OUTCOME_BADGE[outcome]}>
                                    {t(`pages.imports.protocol.outcome.${outcome}`)}
                                </span>
                            </div>
                            <p className="muted" style={{ margin: 0 }}>
                                {t(`pages.imports.protocol.outcome.${outcome}Description`)}
                            </p>

                            {nonzeroCounts.length > 0 && (
                                <div>
                                    <h4 style={{ marginBottom: '0.4rem' }}>{t('pages.imports.protocol.countsTitle')}</h4>
                                    <dl style={{ margin: 0, display: 'grid', gap: '0.2rem' }}>
                                        {nonzeroCounts.map((key) => (
                                            <div key={key} style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem' }}>
                                                <dt>{t(`pages.imports.protocol.counts.${key}`)}</dt>
                                                <dd style={{ margin: 0, fontVariantNumeric: 'tabular-nums', flexShrink: 0 }}>
                                                    {counts?.[key]}
                                                </dd>
                                            </div>
                                        ))}
                                    </dl>
                                    {(counts?.promoted ?? 0) > 0 && (
                                        <p className="muted" style={{ margin: '0.4rem 0 0', fontSize: '0.85rem' }}>
                                            {t('pages.imports.protocol.promotedNote')}
                                        </p>
                                    )}
                                </div>
                            )}

                            {(counts?.held ?? 0) > 0 && !!log.batch_id && (
                                <HeldReadingsPanel key={log.batch_id} importBatch={log.batch_id} />
                            )}

                            {hasDelivery && (
                                <div>
                                    <h4 style={{ marginBottom: '0.4rem' }}>{t('pages.imports.protocol.deliveryTitle')}</h4>
                                    <dl style={{ margin: 0, display: 'grid', gap: '0.2rem', fontSize: '0.9rem' }}>
                                        <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
                                            <dt style={{ fontWeight: 600 }}>{t('pages.imports.protocol.delivery.deliveryId')}:</dt>
                                            <dd style={{ margin: 0, overflowWrap: 'anywhere' }}>{delivery.delivery_id}</dd>
                                        </div>
                                        {delivery.creation && (
                                            <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
                                                <dt style={{ fontWeight: 600 }}>{t('pages.imports.protocol.delivery.creation')}:</dt>
                                                <dd style={{ margin: 0 }}>{formatDateTime(delivery.creation, settings)}</dd>
                                            </div>
                                        )}
                                        {(delivery.status || delivery.reason) && (
                                            <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
                                                <dt style={{ fontWeight: 600 }}>{t('pages.imports.protocol.delivery.profile')}:</dt>
                                                <dd style={{ margin: 0 }}>{[delivery.status, delivery.reason].filter(Boolean).join(' · ')}</dd>
                                            </div>
                                        )}
                                        {(delivery.sender_id || delivery.receiver_id) && (
                                            <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
                                                <dt style={{ fontWeight: 600 }}>{t('pages.imports.protocol.delivery.parties')}:</dt>
                                                <dd style={{ margin: 0 }}>
                                                    {[delivery.sender_id, delivery.receiver_id].filter(Boolean).join(' → ')}
                                                </dd>
                                            </div>
                                        )}
                                    </dl>
                                </div>
                            )}

                            <SdatIssues issues={log.issues ?? []} />
                        </>
                    ) : (
                        <>
                            <DetailRow label={t('pages.imports.protocol.totalRows')}>{log.rows_total ?? '-'}</DetailRow>
                            <DetailRow label={t('pages.imports.protocol.importedRows')}>{log.rows_imported}</DetailRow>
                            <DetailRow label={t('pages.imports.protocol.skippedRows')}>{log.rows_skipped}</DetailRow>

                            {(log.warnings ?? []).length > 0 && (
                                <>
                                    <h4 style={{ marginBottom: '0.4rem' }}>{t('pages.imports.protocol.warnings')}</h4>
                                    <ul style={{ margin: 0, paddingLeft: '1.1rem' }}>
                                        {(log.warnings ?? []).map((entry, index) => (
                                            <li key={`warning-${index}`}>{entry.warning}</li>
                                        ))}
                                    </ul>
                                </>
                            )}

                            <h4 style={{ marginBottom: '0.4rem' }}>{t('pages.imports.protocol.skippedReasons')}</h4>
                            <DataTable
                                data={log.errors ?? []}
                                columns={columns}
                                emptyMessage={t('pages.imports.protocol.noSkippedDetails')}
                            />
                        </>
                    )}
                    {protection === 'overwrite_import_protected' && (
                        <p className="warning-banner">{t('pages.imports.delete.overwriteProtected')}</p>
                    )}
                    {protection === 'quarantine_replace_protected' && (
                        <p className="warning-banner">{t('pages.imports.delete.quarantineProtected')}</p>
                    )}
                </div>
            )}
        </FormModal>
    )
}
