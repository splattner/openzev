import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState, type FormEvent } from 'react'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import {
    faArrowLeft,
    faArrowRight,
    faEye,
    faMagnifyingGlass,
    faPlus,
    faTrash,
    faUpload,
    faXmark,
} from '@fortawesome/free-solid-svg-icons'
import { DataGrid, type GridColDef, type GridRenderCellParams } from '@mui/x-data-grid'
import { ConfirmDialog, useConfirmDialog } from '../components/ConfirmDialog'
import { FormModal } from '../components/FormModal'
import {
    bulkDeleteImportLogs,
    deleteImportLog,
    fetchImportLogs,
    fetchZevs,
    previewCsvImport,
    uploadMeteringFile,
} from '../lib/api'
import { formatDateTime, useAppSettings } from '../lib/appSettings'
import { useAuth } from '../lib/auth'
import { useManagedZev } from '../lib/managedZev'
import { useTranslation } from 'react-i18next'
import { useToast } from '../lib/toast'
import type { ImportLog, ImportPreviewResult } from '../types/api'

type CsvColumnMap = {
    meter_id: string
    timestamp: string
    energy_kwh: string
    direction: string
    energy_start: string
}

const defaultColumnMap: CsvColumnMap = {
    meter_id: 'meter_id',
    timestamp: 'timestamp',
    energy_kwh: 'energy_kwh',
    direction: 'direction',
    energy_start: '4',
}

function Badge({ label, ok }: { label: string; ok: boolean }) {
    return (
        <span className={`badge ${ok ? 'badge-success' : 'badge-danger'}`}>
            {label}
        </span>
    )
}

export function ImportsPage() {
    const queryClient = useQueryClient()
    const { pushToast } = useToast()
    const { dialog, confirm, handleConfirm, handleCancel, isLoading: dialogLoading } = useConfirmDialog()
    const { user } = useAuth()
    const { settings } = useAppSettings()
    const { selectedZevId, selectedZev } = useManagedZev()
    const { t } = useTranslation()
    const isManagedScope = user?.role === 'admin' || user?.role === 'zev_owner'

    const { data, isLoading, isError } = useQuery({ queryKey: ['imports'], queryFn: fetchImportLogs })
    const zevsQuery = useQuery({ queryKey: ['zevs'], queryFn: fetchZevs })

    const [wizardOpen, setWizardOpen] = useState(false)
    const [wizardStep, setWizardStep] = useState<1 | 2>(1)

    const [source, setSource] = useState<'csv' | 'sdatch'>('csv')
    const [file, setFile] = useState<File | null>(null)

    const [zevId, setZevId] = useState('')

    const [hasHeader, setHasHeader] = useState(true)
    const [delimiter, setDelimiter] = useState(',')
    const [formatProfile, setFormatProfile] = useState<'standard' | 'daily_15min'>('daily_15min')
    const [timestampFormat, setTimestampFormat] = useState('%d.%m.%Y')
    const [intervalMinutes, setIntervalMinutes] = useState(15)
    const [valuesCount, setValuesCount] = useState(96)
    const [overwriteExisting, setOverwriteExisting] = useState(false)
    const [columnMap, setColumnMap] = useState<CsvColumnMap>({
        ...defaultColumnMap,
        meter_id: '0',
        timestamp: '3',
        energy_start: '4',
        energy_kwh: '4',
        direction: '',
    })

    const [preview, setPreview] = useState<ImportPreviewResult | null>(null)
    const [selectedLog, setSelectedLog] = useState<ImportLog | null>(null)
    const [showBulkDeleteModal, setShowBulkDeleteModal] = useState(false)
    const [bulkDeleteMode, setBulkDeleteMode] = useState<'period' | 'all'>('period')
    const [bulkDeleteFrom, setBulkDeleteFrom] = useState('')
    const [bulkDeleteTo, setBulkDeleteTo] = useState('')

    const scopedZevId = isManagedScope ? selectedZevId : zevId
    const availableZevs = (zevsQuery.data?.results ?? []).filter((zev) => !isManagedScope || !selectedZevId || zev.id === selectedZevId)
    const importLogs = (data?.results ?? []).filter((log) => !isManagedScope || !selectedZevId || log.zev === selectedZevId)

    const previewMutation = useMutation({
        mutationFn: previewCsvImport,
        onSuccess: (result) => {
            setPreview(result)
            if (result.errors.length > 0) {
                pushToast(t('pages.imports.messages.previewLoadedWithIssues', { count: result.errors.length }), 'error')
            } else {
                pushToast(t('pages.imports.messages.previewLoaded'), 'success')
            }
        },
        onError: () => pushToast(t('pages.imports.messages.previewFailed'), 'error'),
    })

    const uploadMutation = useMutation({
        mutationFn: uploadMeteringFile,
        onSuccess: (result) => {
            pushToast(t('pages.imports.messages.importSuccess', { imported: result.rows_imported, skipped: result.rows_skipped }), 'success')
            setWizardOpen(false)
            setWizardStep(1)
            setFile(null)
            setPreview(null)
            void queryClient.invalidateQueries({ queryKey: ['imports'] })
        },
        onError: (error) => {
            const errorMessage = (error as { response?: { data?: { error?: string } } })?.response?.data?.error
            pushToast(errorMessage || t('pages.imports.messages.importFailed'), 'error')
        },
    })

    const deleteImportMutation = useMutation({
        mutationFn: deleteImportLog,
        onSuccess: (result, importId) => {
            if (selectedLog?.id === importId) {
                setSelectedLog(null)
            }
            pushToast(
                t('pages.imports.messages.deleteSuccess', {
                    logs: result.deleted_logs,
                    readings: result.deleted_readings,
                }),
                'success',
            )
            void queryClient.invalidateQueries({ queryKey: ['imports'] })
        },
        onError: () => pushToast(t('pages.imports.messages.deleteFailed'), 'error'),
    })

    const bulkDeleteMutation = useMutation({
        mutationFn: bulkDeleteImportLogs,
        onSuccess: (result) => {
            setShowBulkDeleteModal(false)
            setBulkDeleteMode('period')
            setBulkDeleteFrom('')
            setBulkDeleteTo('')
            setSelectedLog(null)
            pushToast(
                t('pages.imports.messages.deleteSuccess', {
                    logs: result.deleted_logs,
                    readings: result.deleted_readings,
                }),
                'success',
            )
            void queryClient.invalidateQueries({ queryKey: ['imports'] })
        },
        onError: () => pushToast(t('pages.imports.messages.deleteFailed'), 'error'),
    })

    const canGoStep2 = !!file
    const missingMeteringPoints = preview?.summary.missing_metering_points ?? 0
    const canStartImport = source === 'csv'
        ? !!file && !!preview && missingMeteringPoints === 0 && !!scopedZevId
        : !!file && !!scopedZevId

    const previewRows = useMemo(() => preview?.preview_rows ?? [], [preview])
    const importLogRows = useMemo(
        () =>
            importLogs.map((log) => ({
                ...log,
                created_display: formatDateTime(log.created_at, settings),
                filename_display: log.filename || '-',
                rows_total_display: log.rows_total ?? '-',
            })),
        [importLogs, settings],
    )

    const importLogColumns = useMemo<GridColDef[]>(
        () => [
            {
                field: 'created_display',
                headerName: t('pages.imports.columns.created'),
                flex: 1.2,
                minWidth: 190,
                sortable: false,
                filterable: false,
            },
            {
                field: 'source',
                headerName: t('pages.imports.columns.source'),
                flex: 0.8,
                minWidth: 110,
                sortable: false,
                filterable: false,
            },
            {
                field: 'filename_display',
                headerName: t('pages.imports.columns.filename'),
                flex: 1.3,
                minWidth: 190,
                sortable: false,
                filterable: false,
            },
            {
                field: 'rows_total_display',
                headerName: t('pages.imports.columns.total'),
                flex: 0.6,
                minWidth: 90,
                align: 'right',
                headerAlign: 'right',
                sortable: false,
                filterable: false,
            },
            {
                field: 'rows_imported',
                headerName: t('pages.imports.columns.imported'),
                type: 'number',
                flex: 0.7,
                minWidth: 105,
                align: 'right',
                headerAlign: 'right',
                sortable: false,
                filterable: false,
            },
            {
                field: 'rows_skipped',
                headerName: t('pages.imports.columns.skipped'),
                type: 'number',
                flex: 0.7,
                minWidth: 105,
                align: 'right',
                headerAlign: 'right',
                sortable: false,
                filterable: false,
            },
            {
                field: 'protocol',
                headerName: t('pages.imports.columns.protocol'),
                flex: 0.9,
                minWidth: 150,
                sortable: false,
                filterable: false,
                renderCell: (params: GridRenderCellParams<ImportLog>) => (
                    <button type="button" className="button button-primary" onClick={() => setSelectedLog(params.row)}>
                        <FontAwesomeIcon icon={faEye} fixedWidth />
                        {t('pages.imports.actions.openProtocol')}
                    </button>
                ),
            },
            {
                field: 'actions',
                headerName: t('pages.imports.columns.actions'),
                flex: 0.9,
                minWidth: 150,
                sortable: false,
                filterable: false,
                renderCell: (params: GridRenderCellParams<ImportLog>) => (
                    <button
                        type="button"
                        className="button button-danger"
                        disabled={deleteImportMutation.isPending || dialogLoading}
                        onClick={() => confirm({
                            title: t('pages.imports.delete.singleTitle'),
                            message: t('pages.imports.delete.singleMessage', {
                                filename: params.row.filename || '-',
                                createdAt: formatDateTime(params.row.created_at, settings),
                            }),
                            confirmText: t('pages.imports.delete.confirmAction'),
                            isDangerous: true,
                            onConfirm: () => deleteImportMutation.mutate(params.row.id),
                        })}
                    >
                        <FontAwesomeIcon icon={faTrash} fixedWidth />
                        {t('pages.imports.actions.deleteImport')}
                    </button>
                ),
            },
        ],
        [confirm, deleteImportMutation, dialogLoading, settings, t],
    )

    function resetWizard() {
        setWizardOpen(false)
        setWizardStep(1)
        setSource('csv')
        setFile(null)
        setZevId(isManagedScope ? selectedZevId : '')
        setHasHeader(true)
        setDelimiter(',')
        setFormatProfile('daily_15min')
        setTimestampFormat('%d.%m.%Y')
        setIntervalMinutes(15)
        setValuesCount(96)
        setOverwriteExisting(false)
        setColumnMap(defaultColumnMap)
        setPreview(null)
    }

    function closeBulkDeleteModal() {
        setShowBulkDeleteModal(false)
        setBulkDeleteMode('period')
        setBulkDeleteFrom('')
        setBulkDeleteTo('')
    }

    function handleHasHeaderChange(nextHasHeader: boolean) {
        setHasHeader(nextHasHeader)
        if (nextHasHeader) {
            setDelimiter(',')
            setColumnMap(defaultColumnMap)
            return
        }
        setDelimiter(';')
        setColumnMap({
            meter_id: '0',
            timestamp: '3',
            energy_kwh: '4',
            direction: '',
            energy_start: '4',
        })
    }

    function handleNextStep(event: FormEvent<HTMLFormElement>) {
        event.preventDefault()
        if (!file) {
            pushToast(t('pages.imports.messages.chooseFileFirst'), 'error')
            return
        }
        setWizardStep(2)
    }

    function loadPreview() {
        if (!file) {
            pushToast(t('pages.imports.messages.chooseFileFirst'), 'error')
            return
        }
        previewMutation.mutate({
            file,
            columnMap,
            hasHeader,
            delimiter,
            formatProfile,
            timestampFormat,
            intervalMinutes,
            valuesCount,
        })
    }

    function startImport() {
        if (!file) {
            pushToast(t('pages.imports.messages.chooseFileFirst'), 'error')
            return
        }

        if (source === 'csv') {
            if (!preview) {
                pushToast(t('pages.imports.messages.loadPreviewFirst'), 'error')
                return
            }
            if ((preview.summary.missing_metering_points ?? 0) > 0) {
                pushToast(t('pages.imports.messages.createMissingMetersFirst'), 'error')
                return
            }
            uploadMutation.mutate({
                source,
                zevId: scopedZevId,
                file,
                columnMap,
                hasHeader,
                delimiter,
                formatProfile,
                timestampFormat,
                intervalMinutes,
                valuesCount,
                overwriteExisting,
            })
            return
        }

        if (!scopedZevId) {
            pushToast(t('pages.imports.messages.selectZevForSdatch'), 'error')
            return
        }

        uploadMutation.mutate({ source, zevId: scopedZevId, file })
    }

    function submitBulkDelete() {
        if (bulkDeleteMode === 'period') {
            if (!bulkDeleteFrom || !bulkDeleteTo) {
                pushToast(t('pages.imports.messages.deleteDatesRequired'), 'error')
                return
            }
            if (bulkDeleteTo < bulkDeleteFrom) {
                pushToast(t('pages.imports.messages.deleteDateOrder'), 'error')
                return
            }
        }

        confirm({
            title: t('pages.imports.delete.bulkTitle'),
            message: bulkDeleteMode === 'period'
                ? t('pages.imports.delete.bulkPeriodMessage', { from: bulkDeleteFrom, to: bulkDeleteTo })
                : t('pages.imports.delete.bulkAllMessage'),
            confirmText: t('pages.imports.delete.confirmAction'),
            isDangerous: true,
            onConfirm: () =>
                bulkDeleteMutation.mutate({
                    mode: bulkDeleteMode,
                    dateFrom: bulkDeleteMode === 'period' ? bulkDeleteFrom : undefined,
                    dateTo: bulkDeleteMode === 'period' ? bulkDeleteTo : undefined,
                    zevId: selectedZevId || undefined,
                }),
        })
    }

    if (isLoading) return <div className="card">{t('pages.imports.loading')}</div>
    if (isError) return <div className="card error-banner">{t('pages.imports.loadFailed')}</div>

    return (
        <div className="page-stack">
            <header>
                <h2>{t('pages.imports.title')}</h2>
                <p className="muted">{t('pages.imports.description')}</p>
            </header>

            <section className="card" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '1rem', flexWrap: 'wrap' }}>
                <div>
                    <h3 style={{ marginBottom: '0.3rem' }}>{t('pages.imports.startTitle')}</h3>
                    <p className="muted" style={{ margin: 0 }}>{t('pages.imports.startDescription')}</p>
                </div>
                <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
                    {importLogs.length > 0 && (
                        <button className="button button-danger" type="button" onClick={() => setShowBulkDeleteModal(true)}>
                            <FontAwesomeIcon icon={faTrash} fixedWidth />
                            {t('pages.imports.actions.deleteImports')}
                        </button>
                    )}
                    <button className="button button-primary" onClick={() => setWizardOpen(true)}>
                        <FontAwesomeIcon icon={faPlus} fixedWidth />
                        {t('pages.imports.actions.newImport')}
                    </button>
                </div>
            </section>

            <FormModal isOpen={wizardOpen} title="Import Wizard" onClose={resetWizard} maxWidth="1080px">
                <div className="page-stack" style={{ gap: '0.75rem' }}>
                    <div className="muted" style={{ fontSize: '0.9rem' }}>
                        Step {wizardStep} / 2
                    </div>

                    {wizardStep === 1 && (
                        <form onSubmit={handleNextStep} className="page-stack" style={{ gap: '0.75rem' }}>
                            <label>
                                <span>Source format</span>
                                <select value={source} onChange={(event) => setSource(event.target.value as 'csv' | 'sdatch')}>
                                    <option value="csv">CSV / Excel</option>
                                    <option value="sdatch">SDAT-CH (ebIX XML)</option>
                                </select>
                            </label>

                            <label>
                                <span>Source file</span>
                                <input
                                    type="file"
                                    onChange={(event) => setFile(event.target.files?.[0] ?? null)}
                                    accept={source === 'csv' ? '.csv,.xlsx,.xls' : '.xml'}
                                />
                            </label>

                            <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.6rem' }}>
                                <button type="button" className="button button-secondary" onClick={resetWizard}>
                                    <FontAwesomeIcon icon={faXmark} fixedWidth />
                                    Cancel
                                </button>
                                <button type="submit" className="button button-primary" disabled={!canGoStep2}>
                                    <FontAwesomeIcon icon={faArrowRight} fixedWidth />
                                    Next: Configuration
                                </button>
                            </div>
                        </form>
                    )}

                    {wizardStep === 2 && (
                        <div className="page-stack" style={{ gap: '0.75rem' }}>
                            {source === 'csv' ? (
                                <>
                                    <div className="inline-form grid grid-4">
                                        <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginTop: '1.6rem' }}>
                                            <input
                                                type="checkbox"
                                                checked={hasHeader}
                                                onChange={(event) => handleHasHeaderChange(event.target.checked)}
                                            />
                                            <span>File has header row</span>
                                        </label>
                                        <label>
                                            <span>Delimiter</span>
                                            <input value={delimiter} onChange={(event) => setDelimiter(event.target.value || ',')} placeholder="," />
                                        </label>
                                        <label>
                                            <span>Row format</span>
                                            <select
                                                value={formatProfile}
                                                onChange={(event) => setFormatProfile(event.target.value as 'standard' | 'daily_15min')}
                                            >
                                                <option value="standard">Standard (1 reading per row)</option>
                                                <option value="daily_15min">Daily profile (96x 15-min values)</option>
                                            </select>
                                        </label>
                                        <label>
                                            <span>Date/time format</span>
                                            <input
                                                value={timestampFormat}
                                                onChange={(event) => setTimestampFormat(event.target.value)}
                                                placeholder="%d.%m.%Y"
                                            />
                                        </label>
                                    </div>

                                    <div className="inline-form grid grid-4">
                                        <label>
                                            <span>Meter ID column</span>
                                            <input
                                                value={columnMap.meter_id}
                                                onChange={(event) => setColumnMap((prev) => ({ ...prev, meter_id: event.target.value }))}
                                                placeholder={hasHeader ? 'meter_id' : '0'}
                                            />
                                        </label>
                                        <label>
                                            <span>{formatProfile === 'daily_15min' ? 'Date column' : 'Timestamp column'}</span>
                                            <input
                                                value={columnMap.timestamp}
                                                onChange={(event) => setColumnMap((prev) => ({ ...prev, timestamp: event.target.value }))}
                                                placeholder={hasHeader ? 'timestamp' : '3'}
                                            />
                                        </label>

                                        {formatProfile === 'standard' ? (
                                            <>
                                                <label>
                                                    <span>Energy column</span>
                                                    <input
                                                        value={columnMap.energy_kwh}
                                                        onChange={(event) => setColumnMap((prev) => ({ ...prev, energy_kwh: event.target.value }))}
                                                        placeholder={hasHeader ? 'energy_kwh' : '4'}
                                                    />
                                                </label>
                                                <label>
                                                    <span>Direction column (optional)</span>
                                                    <input
                                                        value={columnMap.direction}
                                                        onChange={(event) => setColumnMap((prev) => ({ ...prev, direction: event.target.value }))}
                                                        placeholder={hasHeader ? 'direction' : '5'}
                                                    />
                                                </label>
                                            </>
                                        ) : (
                                            <>
                                                <label>
                                                    <span>First interval column</span>
                                                    <input
                                                        value={columnMap.energy_start}
                                                        onChange={(event) => setColumnMap((prev) => ({ ...prev, energy_start: event.target.value }))}
                                                        placeholder={hasHeader ? 'energy_start' : '4'}
                                                    />
                                                </label>
                                                <label>
                                                    <span>Intervals per row</span>
                                                    <input type="number" min={1} max={200} value={valuesCount} onChange={(event) => setValuesCount(Number(event.target.value || 96))} />
                                                </label>
                                                <label>
                                                    <span>Minutes per interval</span>
                                                    <input type="number" min={1} max={240} value={intervalMinutes} onChange={(event) => setIntervalMinutes(Number(event.target.value || 15))} />
                                                </label>
                                            </>
                                        )}
                                    </div>

                                    <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                        <input
                                            type="checkbox"
                                            checked={overwriteExisting}
                                            onChange={(event) => setOverwriteExisting(event.target.checked)}
                                        />
                                        <span>Overwrite existing data for same metering point + timestamp + direction</span>
                                    </label>

                                    <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                                        <button type="button" className="button button-primary" onClick={loadPreview} disabled={previewMutation.isPending || !file}>
                                            <FontAwesomeIcon icon={faMagnifyingGlass} fixedWidth />
                                            {previewMutation.isPending ? 'Loading preview...' : 'Load Preview'}
                                        </button>
                                        {preview && (
                                            <>
                                                <Badge label={`${preview.summary.existing_metering_points} meter found`} ok={preview.summary.existing_metering_points > 0} />
                                                <Badge label={`${preview.summary.missing_metering_points} missing`} ok={preview.summary.missing_metering_points === 0} />
                                            </>
                                        )}
                                    </div>

                                    {preview && missingMeteringPoints > 0 && (
                                        <div className="error-banner" style={{ marginTop: '0.4rem' }}>
                                            {missingMeteringPoints} metering point(s) from this file are missing. Please create them first; import start is blocked.
                                        </div>
                                    )}

                                    {preview?.errors?.length ? (
                                        <div className="error-banner" style={{ marginTop: '0.4rem' }}>
                                            <ul style={{ margin: 0, paddingLeft: '1.1rem' }}>
                                                {preview.errors.slice(0, 8).map((entry, index) => (
                                                    <li key={`${entry.row ?? 'general'}-${index}`}>
                                                        {entry.row ? `Row ${entry.row}: ` : ''}{entry.error}
                                                    </li>
                                                ))}
                                            </ul>
                                        </div>
                                    ) : null}

                                    {previewRows.length > 0 && (
                                        <div style={{ maxHeight: 250, overflow: 'auto', border: '1px solid var(--color-border, #ddd)', borderRadius: 6 }}>
                                            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                                                <thead>
                                                    <tr>
                                                        <th style={{ textAlign: 'left', padding: '0.4rem 0.6rem' }}>Row</th>
                                                        <th style={{ textAlign: 'left', padding: '0.4rem 0.6rem' }}>Meter ID</th>
                                                        <th style={{ textAlign: 'left', padding: '0.4rem 0.6rem' }}>Status</th>
                                                        <th style={{ textAlign: 'left', padding: '0.4rem 0.6rem' }}>Date/Timestamp</th>
                                                        <th style={{ textAlign: 'left', padding: '0.4rem 0.6rem' }}>Existing data</th>
                                                    </tr>
                                                </thead>
                                                <tbody>
                                                    {previewRows.map((row) => (
                                                        <tr key={`${row.row}-${row.meter_id ?? 'empty'}`} style={{ borderTop: '1px solid var(--color-border, #eee)' }}>
                                                            <td style={{ padding: '0.4rem 0.6rem' }}>{row.row}</td>
                                                            <td style={{ padding: '0.4rem 0.6rem' }}>{row.meter_id ?? '-'}</td>
                                                            <td style={{ padding: '0.4rem 0.6rem' }}>
                                                                <Badge label={row.metering_point_exists ? 'Exists' : 'Missing'} ok={row.metering_point_exists} />
                                                            </td>
                                                            <td style={{ padding: '0.4rem 0.6rem' }}>{row.timestamp ?? '-'}</td>
                                                            <td style={{ padding: '0.4rem 0.6rem' }}>
                                                                {row.existing_data == null ? '-' : row.existing_data ? 'Yes' : 'No'}
                                                            </td>
                                                        </tr>
                                                    ))}
                                                </tbody>
                                            </table>
                                        </div>
                                    )}
                                </>
                            ) : (
                                <>
                                    <p className="muted" style={{ margin: 0 }}>
                                        SDAT-CH import currently requires selecting the target ZEV owner scope.
                                    </p>
                                    <label>
                                        <span>ZEV</span>
                                        {isManagedScope ? (
                                            <input value={selectedZev?.name ?? 'No ZEV selected'} disabled />
                                        ) : (
                                            <select value={zevId} onChange={(event) => setZevId(event.target.value)}>
                                                <option value="">Select ZEV</option>
                                                {availableZevs.map((zev) => (
                                                    <option key={zev.id} value={zev.id}>{zev.name}</option>
                                                ))}
                                            </select>
                                        )}
                                    </label>
                                </>
                            )}

                            <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.6rem', marginTop: '0.4rem' }}>
                                <button type="button" className="button button-secondary" onClick={() => setWizardStep(1)}>
                                    <FontAwesomeIcon icon={faArrowLeft} fixedWidth />
                                    Back
                                </button>
                                <button type="button" className="button button-primary" onClick={startImport} disabled={uploadMutation.isPending || !canStartImport}>
                                    <FontAwesomeIcon icon={faUpload} fixedWidth />
                                    {uploadMutation.isPending ? 'Importing...' : 'Start Import'}
                                </button>
                            </div>
                        </div>
                    )}
                </div>
            </FormModal>

            <div className="table-card" style={{ width: '100%' }}>
                <DataGrid
                    rows={importLogRows}
                    columns={importLogColumns}
                    getRowId={(row) => row.id}
                    disableRowSelectionOnClick
                    disableColumnFilter
                    disableColumnSorting
                    disableColumnMenu
                    hideFooterSelectedRowCount
                    pageSizeOptions={[10, 25, 50, 100]}
                    initialState={{
                        pagination: {
                            paginationModel: { pageSize: 25, page: 0 },
                        },
                    }}
                    localeText={{
                        noRowsLabel: t('pages.imports.noRows'),
                    }}
                    sx={{
                        border: 0,
                        '& .MuiDataGrid-columnHeaders': {
                            backgroundColor: '#f8fafc',
                        },
                    }}
                />
            </div>

            <FormModal isOpen={showBulkDeleteModal} title={t('pages.imports.delete.bulkModalTitle')} onClose={closeBulkDeleteModal} maxWidth="640px">
                <div className="page-stack" style={{ gap: '1rem' }}>
                    <p className="muted" style={{ margin: 0 }}>{t('pages.imports.delete.bulkDescription')}</p>

                    <label>
                        <span>{t('pages.imports.delete.modeLabel')}</span>
                        <select value={bulkDeleteMode} onChange={(event) => setBulkDeleteMode(event.target.value as 'period' | 'all')}>
                            <option value="period">{t('pages.imports.delete.modePeriod')}</option>
                            <option value="all">{t('pages.imports.delete.modeAll')}</option>
                        </select>
                    </label>

                    {bulkDeleteMode === 'period' && (
                        <div className="inline-form grid grid-2">
                            <label>
                                <span>{t('pages.imports.delete.dateFrom')}</span>
                                <input type="date" value={bulkDeleteFrom} onChange={(event) => setBulkDeleteFrom(event.target.value)} />
                            </label>
                            <label>
                                <span>{t('pages.imports.delete.dateTo')}</span>
                                <input type="date" value={bulkDeleteTo} onChange={(event) => setBulkDeleteTo(event.target.value)} />
                            </label>
                        </div>
                    )}

                    <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem' }}>
                        <button className="button button-secondary" type="button" onClick={closeBulkDeleteModal}>
                            <FontAwesomeIcon icon={faXmark} fixedWidth />
                            {t('common.cancel')}
                        </button>
                        <button className="button button-danger" type="button" onClick={submitBulkDelete} disabled={bulkDeleteMutation.isPending || dialogLoading}>
                            <FontAwesomeIcon icon={faTrash} fixedWidth />
                            {t('pages.imports.delete.confirmAction')}
                        </button>
                    </div>
                </div>
            </FormModal>

            <FormModal isOpen={!!selectedLog} title={t('pages.imports.protocol.title')} onClose={() => setSelectedLog(null)}>
                {selectedLog && (
                    <div className="page-stack" style={{ gap: '0.75rem' }}>
                        <div><strong>{t('pages.imports.protocol.created')}</strong> {formatDateTime(selectedLog.created_at, settings)}</div>
                        <div><strong>{t('pages.imports.protocol.source')}</strong> {selectedLog.source}</div>
                        <div><strong>{t('pages.imports.protocol.filename')}</strong> {selectedLog.filename || '-'}</div>
                        <div><strong>{t('pages.imports.protocol.totalRows')}</strong> {selectedLog.rows_total ?? '-'}</div>
                        <div><strong>{t('pages.imports.protocol.importedRows')}</strong> {selectedLog.rows_imported}</div>
                        <div><strong>{t('pages.imports.protocol.skippedRows')}</strong> {selectedLog.rows_skipped}</div>

                        <h4 style={{ marginBottom: '0.4rem' }}>{t('pages.imports.protocol.skippedReasons')}</h4>
                        {(selectedLog.errors?.length ?? 0) === 0 ? (
                            <p className="muted" style={{ margin: 0 }}>{t('pages.imports.protocol.noSkippedDetails')}</p>
                        ) : (
                            <div style={{ maxHeight: 300, overflow: 'auto', border: '1px solid var(--color-border, #ddd)', borderRadius: 6 }}>
                                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                                    <thead>
                                        <tr>
                                            <th style={{ textAlign: 'left', padding: '0.5rem 0.75rem' }}>{t('pages.imports.protocol.row')}</th>
                                            <th style={{ textAlign: 'left', padding: '0.5rem 0.75rem' }}>{t('pages.imports.protocol.reason')}</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {selectedLog.errors?.map((entry, index) => (
                                            <tr key={`${entry.row ?? 'global'}-${index}`} style={{ borderTop: '1px solid var(--color-border, #eee)' }}>
                                                <td style={{ padding: '0.5rem 0.75rem', verticalAlign: 'top' }}>
                                                    {entry.row ?? t('pages.imports.protocol.general')}
                                                </td>
                                                <td style={{ padding: '0.5rem 0.75rem' }}>{entry.error}</td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        )}
                    </div>
                )}
            </FormModal>

            {dialog && (
                <ConfirmDialog {...dialog} isLoading={dialogLoading} onConfirm={handleConfirm} onCancel={handleCancel} />
            )}
        </div>
    )
}
