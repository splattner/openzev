import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { formatShortDate, useAppSettings } from '../../lib/appSettings'
import { fetchImportLog } from '../../lib/api/metering'
import { queryKeys } from '../../lib/api/queryKeys'
import { formatMeteringTimestamp } from '../../lib/meteringLabels'
import type { ImportLog } from '../../types/api'

// Client-side pagination bounds rendering, not storage or transfer.
const CHANGE_PAGE_SIZE = 50

// List responses omit reading_changes; load retained events from detail.
export function CorrectionHistory({ log, focusOnLoad, period }: {
    log: ImportLog
    focusOnLoad?: boolean
    period?: { from: string; to: string }
}) {
    const { t } = useTranslation()
    const { settings } = useAppSettings()
    const [page, setPage] = useState(0)
    const sectionRef = useRef<HTMLElement>(null)
    const queryClient = useQueryClient()
    const queryKey = queryKeys.metering.importLog(log.id)

    const detailQuery = useQuery<ImportLog | null>({
        queryKey,
        queryFn: async (context) => {
            try {
                return await fetchImportLog(log.id)
            } catch (error) {
                const status = (error as { response?: { status?: number } })?.response?.status
                // Read the signal only on failure so pending reads survive StrictMode remounts.
                if (!context.signal.aborted && [401, 403, 404].includes(status ?? 0)) queryClient.setQueryData(queryKey, null)
                throw error
            }
        },
        retry: false,
        staleTime: 60_000,
    })
    const detail = detailQuery.data
    const unavailable = !detail
    const changes = detail?.reading_changes ?? []
    const truncated = (detail?.result_counts ?? log.result_counts)?.reading_changes_truncated === true
    const pageCount = Math.max(1, Math.ceil(changes.length / CHANGE_PAGE_SIZE))
    const currentPage = Math.min(page, pageCount - 1)
    const visibleChanges = changes.slice(currentPage * CHANGE_PAGE_SIZE, (currentPage + 1) * CHANGE_PAGE_SIZE)
    const metadataOnly = changes.length > 0 && changes.every((change) => change.kind === 'metadata')

    useEffect(() => {
        if (focusOnLoad && !detailQuery.isPending) {
            // Follow the link after the dialog's initial focus has settled.
            const frame = requestAnimationFrame(() => {
                const section = sectionRef.current
                if (!section || (document.activeElement !== document.body && document.activeElement !== section.closest('[role="dialog"]'))) return
                section.focus()
                section.scrollIntoView({ block: 'start' })
            })
            return () => cancelAnimationFrame(frame)
        }
    }, [focusOnLoad, detailQuery.isPending])

    const retryButton = (
        <button type="button" className="button button-secondary button-compact"
            disabled={detailQuery.isFetching} onClick={() => void detailQuery.refetch()}>
            {t('common.retry')}
        </button>
    )

    return (
        <section id="correction-history" ref={sectionRef} tabIndex={-1} aria-labelledby="correction-history-title" className="correction-history">
            <h4 id="correction-history-title" className="correction-history-title">{t('pages.imports.protocol.correctionsTitle')}</h4>
            {period && (
                <p className="muted">
                    {t('pages.imports.protocol.correctionsPeriod', {
                        from: formatShortDate(period.from, settings),
                        to: formatShortDate(period.to, settings),
                    })}
                </p>
            )}
            {truncated && (
                <p className="warning-banner correction-history-note">
                    {t('pages.imports.protocol.correctionsTruncated')}
                </p>
            )}
            {detailQuery.isLoading ? (
                <p className="muted">
                    {t('pages.imports.protocol.correctionsLoading')}
                </p>
            ) : unavailable ? (
                <p className="muted">
                    {t('pages.imports.protocol.correctionsUnavailable')}{' '}{retryButton}
                </p>
            ) : (
                <>
                    {detailQuery.isError && (
                        <p className="warning-banner">
                            {t('pages.imports.protocol.correctionsRefreshFailed')}{' '}{retryButton}
                        </p>
                    )}
                    <p className="muted correction-history-note">
                        {t('pages.imports.protocol.correctionsRetained', { count: changes.length })}
                    </p>
                    {metadataOnly && <p className="muted">{t('pages.imports.protocol.correctionsMetadataOnly')}</p>}
                    {changes.length === 0 ? (
                        <p className="muted">
                            {!truncated && detail?.result_status === 'unchanged'
                                ? t('pages.imports.protocol.correctionsNoChangesConfirmed')
                                : t('pages.imports.protocol.correctionsNoneRecorded')}
                        </p>
                    ) : (
                        <>
                            <div className="table-scroll" role="region" aria-label={t('pages.imports.protocol.correctionsTable')} tabIndex={0}>
                                <table className="data-table correction-history-table">
                                    <thead>
                                        <tr>
                                            <th>{t('pages.imports.protocol.corrections.meter')}</th>
                                            <th>{t('pages.imports.protocol.corrections.interval')}</th>
                                            <th>{t('pages.imports.protocol.corrections.direction')}</th>
                                            <th>{t('pages.imports.protocol.corrections.kind')}</th>
                                            <th>{t('pages.imports.protocol.corrections.values')}</th>
                                            <th>{t('pages.imports.protocol.corrections.document')}</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {visibleChanges.map((change, index) => (
                                            <tr key={`${change.metering_point}-${change.timestamp}-${change.direction}-${index}`}>
                                                <td>{change.meter_id || '—'}</td>
                                                <td><time dateTime={change.timestamp}>{formatMeteringTimestamp(change.timestamp, settings)}</time></td>
                                                <td>
                                                    {change.direction === 'in'
                                                        ? t('pages.imports.preview.directionIn')
                                                        : t('pages.imports.preview.directionOut')}
                                                </td>
                                                <td>
                                                    {t(`pages.imports.protocol.corrections.kinds.${change.kind}`)}
                                                    {change.promoted && (
                                                        <div className="muted correction-history-promoted">
                                                            {t('pages.imports.protocol.corrections.promoted')}
                                                        </div>
                                                    )}
                                                </td>
                                                <td className="correction-history-values">
                                                    <span className="muted">{change.old_energy === null
                                                        ? t('pages.imports.protocol.corrections.noPreviousValue')
                                                        : `${change.old_energy} kWh`}</span>
                                                    {' → '}
                                                    <strong>{`${change.new_energy} kWh`}</strong>
                                                </td>
                                                <td className="correction-history-document">
                                                    {change.source_document_id || '—'}
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                            {changes.length > CHANGE_PAGE_SIZE && (
                                <div className="actions-row actions-row-end correction-history-pagination">
                                    <button
                                        type="button"
                                        className="button button-secondary button-compact"
                                        aria-label={t('common.pagination.previous')}
                                        onClick={() => setPage(currentPage - 1)}
                                        disabled={currentPage === 0}
                                    >
                                        ‹
                                    </button>
                                    <span className="muted">
                                        {currentPage + 1} / {pageCount}
                                    </span>
                                    <button
                                        type="button"
                                        className="button button-secondary button-compact"
                                        aria-label={t('common.pagination.next')}
                                        onClick={() => setPage(currentPage + 1)}
                                        disabled={currentPage >= pageCount - 1}
                                    >
                                        ›
                                    </button>
                                </div>
                            )}
                            <p className="muted correction-history-footnote">
                                {t('pages.imports.protocol.corrections.metadataNotRecorded')}
                            </p>
                        </>
                    )}
                </>
            )}
        </section>
    )
}
