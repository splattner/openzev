import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { DataTable, type ColumnDef } from '../../components/DataTable'
import { FormModal } from '../../components/FormModal'
import { formatDateTime, useAppSettings } from '../../lib/appSettings'
import type { ImportLog } from '../../types/api'

export function ImportProtocolModal({ log, onClose }: { log: ImportLog | null; onClose: () => void }) {
    const { t } = useTranslation()
    const { settings } = useAppSettings()

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

    return (
        <FormModal isOpen={!!log} title={t('pages.imports.protocol.title')} onClose={onClose}>
            {log && (
                <div className="page-stack" style={{ gap: '0.75rem' }}>
                    <div><strong>{t('pages.imports.protocol.created')}</strong> {formatDateTime(log.created_at, settings)}</div>
                    <div><strong>{t('pages.imports.protocol.source')}</strong> {log.source}</div>
                    <div><strong>{t('pages.imports.protocol.zev')}</strong> {log.zev_name || log.zev || '-'}</div>
                    <div><strong>{t('pages.imports.protocol.importedBy')}</strong> {log.imported_by_display || '-'}</div>
                    <div><strong>{t('pages.imports.protocol.batchId')}</strong> {log.batch_id || '-'}</div>
                    <div><strong>{t('pages.imports.protocol.filename')}</strong> {log.filename || '-'}</div>
                    <div><strong>{t('pages.imports.protocol.totalRows')}</strong> {log.rows_total ?? '-'}</div>
                    <div><strong>{t('pages.imports.protocol.importedRows')}</strong> {log.rows_imported}</div>
                    <div><strong>{t('pages.imports.protocol.skippedRows')}</strong> {log.rows_skipped}</div>

                    {log.rows_overwritten > 0 && (
                        <p className="warning-banner">{t('pages.imports.delete.overwriteProtected')}</p>
                    )}

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
                        initialPageSize={10}
                        emptyMessage={t('pages.imports.protocol.noSkippedDetails')}
                    />
                </div>
            )}
        </FormModal>
    )
}
