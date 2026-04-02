import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState, type FormEvent } from 'react'
import { DataGrid, type GridColDef, type GridRenderCellParams } from '@mui/x-data-grid'
import { FormModal } from '../components/FormModal'
import {
    fetchImportLogs,
    fetchZevs,
    previewCsvImport,
    uploadMeteringFile,
} from '../lib/api'
import { formatDateTime, useAppSettings } from '../lib/appSettings'
import { useAuth } from '../lib/auth'
import { useManagedZev } from '../lib/managedZev'
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
    const { user } = useAuth()
    const { settings } = useAppSettings()
    const { selectedZevId, selectedZev } = useManagedZev()
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

    const scopedZevId = isManagedScope ? selectedZevId : zevId
    const availableZevs = (zevsQuery.data?.results ?? []).filter((zev) => !isManagedScope || !selectedZevId || zev.id === selectedZevId)
    const importLogs = (data?.results ?? []).filter((log) => !isManagedScope || !selectedZevId || log.zev === selectedZevId)

    const previewMutation = useMutation({
        mutationFn: previewCsvImport,
        onSuccess: (result) => {
            setPreview(result)
            if (result.errors.length > 0) {
                pushToast(`Preview loaded with ${result.errors.length} issue(s).`, 'error')
            } else {
                pushToast('Preview loaded.', 'success')
            }
        },
        onError: () => pushToast('Failed to load preview.', 'error'),
    })

    const uploadMutation = useMutation({
        mutationFn: uploadMeteringFile,
        onSuccess: (result) => {
            pushToast(`Imported ${result.rows_imported} rows (${result.rows_skipped} skipped).`, 'success')
            setWizardOpen(false)
            setWizardStep(1)
            setFile(null)
            setPreview(null)
            void queryClient.invalidateQueries({ queryKey: ['imports'] })
        },
        onError: (error) => {
            const errorMessage = (error as { response?: { data?: { error?: string } } })?.response?.data?.error
            pushToast(errorMessage || 'Import failed.', 'error')
        },
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
                headerName: 'Created',
                flex: 1.2,
                minWidth: 190,
                sortable: false,
                filterable: false,
            },
            {
                field: 'source',
                headerName: 'Source',
                flex: 0.8,
                minWidth: 110,
                sortable: false,
                filterable: false,
            },
            {
                field: 'filename_display',
                headerName: 'Filename',
                flex: 1.3,
                minWidth: 190,
                sortable: false,
                filterable: false,
            },
            {
                field: 'rows_total_display',
                headerName: 'Total',
                flex: 0.6,
                minWidth: 90,
                align: 'right',
                headerAlign: 'right',
                sortable: false,
                filterable: false,
            },
            {
                field: 'rows_imported',
                headerName: 'Imported',
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
                headerName: 'Skipped',
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
                headerName: 'Protocol',
                flex: 0.9,
                minWidth: 150,
                sortable: false,
                filterable: false,
                renderCell: (params: GridRenderCellParams<ImportLog>) => (
                    <button type="button" className="button button-primary" onClick={() => setSelectedLog(params.row)}>
                        Open protocol
                    </button>
                ),
            },
        ],
        [],
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
            pushToast('Please choose a file first.', 'error')
            return
        }
        setWizardStep(2)
    }

    function loadPreview() {
        if (!file) {
            pushToast('Please choose a file first.', 'error')
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
            pushToast('Please choose a file first.', 'error')
            return
        }

        if (source === 'csv') {
            if (!preview) {
                pushToast('Load preview before starting import.', 'error')
                return
            }
            if ((preview.summary.missing_metering_points ?? 0) > 0) {
                pushToast('Create missing metering points before starting import.', 'error')
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
            pushToast('Please select a ZEV for SDAT-CH import.', 'error')
            return
        }

        uploadMutation.mutate({ source, zevId: scopedZevId, file })
    }

    if (isLoading) return <div className="card">Loading import logs...</div>
    if (isError) return <div className="card error-banner">Failed to load import logs.</div>

    return (
        <div className="page-stack">
            <header>
                <h2>Metering Imports</h2>
                <p className="muted">Guided import wizard with preview and import protocol.</p>
            </header>

            <section className="card" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '1rem', flexWrap: 'wrap' }}>
                <div>
                    <h3 style={{ marginBottom: '0.3rem' }}>Start new import</h3>
                    <p className="muted" style={{ margin: 0 }}>Step-by-step flow with column mapping and preview checks.</p>
                </div>
                <button className="button button-primary" onClick={() => setWizardOpen(true)}>
                    + New Import
                </button>
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
                                    Cancel
                                </button>
                                <button type="submit" className="button button-primary" disabled={!canGoStep2}>
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
                                    Back
                                </button>
                                <button type="button" className="button button-primary" onClick={startImport} disabled={uploadMutation.isPending || !canStartImport}>
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
                        noRowsLabel: 'No import logs yet.',
                    }}
                    sx={{
                        border: 0,
                        '& .MuiDataGrid-columnHeaders': {
                            backgroundColor: '#f8fafc',
                        },
                    }}
                />
            </div>

            <FormModal isOpen={!!selectedLog} title="Import protocol" onClose={() => setSelectedLog(null)}>
                {selectedLog && (
                    <div className="page-stack" style={{ gap: '0.75rem' }}>
                        <div><strong>Created:</strong> {formatDateTime(selectedLog.created_at, settings)}</div>
                        <div><strong>Source:</strong> {selectedLog.source}</div>
                        <div><strong>Filename:</strong> {selectedLog.filename || '-'}</div>
                        <div><strong>Total rows:</strong> {selectedLog.rows_total ?? '-'}</div>
                        <div><strong>Imported rows:</strong> {selectedLog.rows_imported}</div>
                        <div><strong>Skipped rows:</strong> {selectedLog.rows_skipped}</div>

                        <h4 style={{ marginBottom: '0.4rem' }}>Skipped row reasons</h4>
                        {(selectedLog.errors?.length ?? 0) === 0 ? (
                            <p className="muted" style={{ margin: 0 }}>No skipped row details for this import.</p>
                        ) : (
                            <div style={{ maxHeight: 300, overflow: 'auto', border: '1px solid var(--color-border, #ddd)', borderRadius: 6 }}>
                                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                                    <thead>
                                        <tr>
                                            <th style={{ textAlign: 'left', padding: '0.5rem 0.75rem' }}>Row</th>
                                            <th style={{ textAlign: 'left', padding: '0.5rem 0.75rem' }}>Reason</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {selectedLog.errors?.map((entry, index) => (
                                            <tr key={`${entry.row ?? 'global'}-${index}`} style={{ borderTop: '1px solid var(--color-border, #eee)' }}>
                                                <td style={{ padding: '0.5rem 0.75rem', verticalAlign: 'top' }}>
                                                    {entry.row ?? 'General'}
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
        </div>
    )
}
