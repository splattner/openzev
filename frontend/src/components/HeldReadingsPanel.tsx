import { useQuery } from '@tanstack/react-query'
import { faChevronDown } from '@fortawesome/free-solid-svg-icons'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { fetchHeldMeteringReadings } from '../lib/api/metering'
import { queryKeys } from '../lib/api/queryKeys'
import { useAppSettings } from '../lib/appSettings'
import { conditionLabel, formatMeteringTimestamp } from '../lib/meteringLabels'
import { formatNumber } from '../lib/numbers'
import type { HeldMeteringReading } from '../types/api'

export function HeldReadingsPanel({
    meteringPointId,
    importBatch,
    dateFrom,
    dateTo,
}: {
    /** Omit on a surface that is already scoped by import instead. */
    meteringPointId?: string
    importBatch?: string
    dateFrom?: string
    dateTo?: string
}) {
    const { t } = useTranslation()
    const { settings } = useAppSettings()
    const [open, setOpen] = useState(false)
    const [page, setPage] = useState(1)
    const visible = !!importBatch || open

    const query = useQuery({
        queryKey: queryKeys.metering.heldReadings(
            meteringPointId ?? '',
            dateFrom ?? '',
            dateTo ?? '',
            importBatch ?? '',
            page,
        ),
        queryFn: () =>
            fetchHeldMeteringReadings({ meteringPoint: meteringPointId, importBatch, dateFrom, dateTo, page }),
        enabled: visible && (!!meteringPointId || !!importBatch),
    })

    const rows: HeldMeteringReading[] = query.data?.results ?? []
    const count = query.data?.count ?? 0
    const pageSize = query.data?.page_size ?? 1
    const pageCount = Math.max(1, Math.ceil(count / pageSize))
    const title = t(importBatch ? 'pages.imports.protocol.heldTitle' : 'pages.meteringData.rawTable.heldTitle')

    return (
        <div className="held-readings">
            <div className="actions-row actions-row-wrap">
                <h4>{title}</h4>
                {!importBatch && (
                    <button
                        type="button"
                        className="button button-ghost button-compact disclosure-toggle"
                        aria-expanded={open}
                        onClick={() => setOpen((value) => !value)}
                    >
                        <FontAwesomeIcon icon={faChevronDown} className="disclosure-toggle-icon" fixedWidth aria-hidden="true" />
                        {open
                            ? t('pages.meteringData.rawTable.heldHide')
                            : t('pages.meteringData.rawTable.heldShow')}
                        {open && query.data ? ` (${count})` : ''}
                    </button>
                )}
            </div>
            <p className="muted mt-0">
                {t(importBatch ? 'pages.imports.protocol.heldDescription' : 'pages.meteringData.rawTable.heldDescription')}
            </p>

            {visible && (
                <>
                    {query.isLoading ? (
                        <div className="held-readings-status muted">
                            {t('pages.meteringData.rawTable.heldLoading')}
                        </div>
                    ) : query.isError ? (
                        <div className="error-banner">
                            {t('pages.meteringData.rawTable.heldError')}{' '}
                            <button type="button" className="button button-secondary button-compact"
                                disabled={query.isFetching} onClick={() => void query.refetch()}>
                                {t('common.retry')}
                            </button>
                        </div>
                    ) : rows.length === 0 ? (
                        <div className="held-readings-status muted">
                            {t(importBatch ? 'pages.imports.protocol.heldEmpty' : 'pages.meteringData.rawTable.heldEmpty')}
                        </div>
                    ) : (
                        <>
                            <p className="held-readings-note">
                                {t('pages.meteringData.rawTable.heldCoexistNote')}
                            </p>
                            <div className="held-readings-scroll" role="region" aria-label={title} tabIndex={0}>
                                <table className="held-readings-table">
                                    <thead>
                                        <tr>
                                            <th>{t('pages.meteringData.rawTable.heldInterval')}</th>
                                            <th>{t('pages.meteringData.rawTable.heldDirection')}</th>
                                            <th className="held-readings-num">
                                                {t('pages.meteringData.rawTable.heldEnergy')}
                                            </th>
                                            <th>{t('pages.meteringData.rawTable.heldQuality')}</th>
                                            <th className="held-readings-num">
                                                {t('pages.meteringData.rawTable.heldAccepted')}
                                            </th>
                                            <th>{t('pages.meteringData.rawTable.heldPurpose')}</th>
                                            <th>{t('pages.meteringData.rawTable.heldSource')}</th>
                                            <th>{t('pages.meteringData.rawTable.heldRecorded')}</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {rows.map((row) => (
                                            <tr key={row.id}>
                                                <td>
                                                    <div>{row.meter_id}</div>
                                                    <time dateTime={row.timestamp}>{formatMeteringTimestamp(row.timestamp, settings)}</time>
                                                </td>
                                                <td>
                                                    {row.direction === 'in'
                                                        ? t('pages.imports.preview.directionIn')
                                                        : t('pages.meteringData.rawTable.heldDirectionOut')}
                                                </td>
                                                <td className="held-readings-num">
                                                    {formatNumber(Number(row.energy_kwh), {
                                                        minDecimals: 4,
                                                        maxDecimals: 4,
                                                    })}
                                                </td>
                                                <td>
                                                    {conditionLabel(row.condition, t)}
                                                </td>
                                                <td className="held-readings-num">
                                                    {row.accepted_energy_kwh !== null
                                                        ? `${formatNumber(Number(row.accepted_energy_kwh), {
                                                              minDecimals: 4,
                                                              maxDecimals: 4,
                                                          })} kWh`
                                                        : t('pages.meteringData.rawTable.heldNoAccepted')}
                                                </td>
                                                <td>{row.business_reason === 'E88'
                                                    ? t('pages.meteringData.rawTable.heldPurposeBilling')
                                                    : row.business_reason === 'C38'
                                                        ? t('pages.meteringData.rawTable.heldPurposeInformation')
                                                        : row.business_reason || '—'}</td>
                                                <td className="held-readings-source">
                                                    <div>{row.source_delivery_id || row.import_source}</div>
                                                    {row.source_document_id && <div>{row.source_document_id}</div>}
                                                    {row.source_creation && (
                                                        <div className="muted">
                                                            {t('pages.meteringData.rawTable.heldDeliveryCreated')}:{' '}
                                                            {formatMeteringTimestamp(row.source_creation, settings)}
                                                        </div>
                                                    )}
                                                </td>
                                                <td>{formatMeteringTimestamp(row.created_at, settings)}</td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                            {count > pageSize && (
                                <div className="data-table-footer actions-row actions-row-end muted">
                                    <span>
                                        {t('common.pagination.range', {
                                            from: (page - 1) * pageSize + 1,
                                            to: Math.min(page * pageSize, count),
                                            total: count,
                                        })}
                                    </span>
                                    <span className="flex-1" />
                                    <button
                                        className="button button-secondary button-compact"
                                        type="button"
                                        aria-label={t('common.pagination.previous')}
                                        onClick={() => setPage((value) => value - 1)}
                                        disabled={page === 1}
                                    >
                                        ‹
                                    </button>
                                    <span>
                                        {page} / {pageCount}
                                    </span>
                                    <button
                                        className="button button-secondary button-compact"
                                        type="button"
                                        aria-label={t('common.pagination.next')}
                                        onClick={() => setPage((value) => value + 1)}
                                        disabled={page >= pageCount}
                                    >
                                        ›
                                    </button>
                                </div>
                            )}
                        </>
                    )}
                    {page > 1 && (query.isError || (!query.isLoading && rows.length === 0)) && (
                        <button type="button" className="button button-secondary button-compact"
                            onClick={() => setPage(1)}>
                            {t('pages.meteringData.rawTable.heldFirstPage')}
                        </button>
                    )}
                </>
            )}
        </div>
    )
}
