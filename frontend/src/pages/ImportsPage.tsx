import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useRef, useState, type FormEvent } from 'react'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import {
    faEye,
    faPlus,
    faTrash,
} from '@fortawesome/free-solid-svg-icons'
import { ConfirmDialog, useConfirmDialog } from '../components/ConfirmDialog'
import { ActionMenu } from '../components/ActionMenu'
import type { ColumnDef, ColumnFiltersState } from '../components/DataTable'
import {
    bulkDeleteImportLogs,
    deleteImportLog,
    fetchImportLogs,
    previewCsvImport,
    uploadMeteringFile,
} from '../lib/api/metering'
import { queryKeys } from '../lib/api/queryKeys'
import { formatDateTime, useAppSettings } from '../lib/appSettings'
import { useManagedZev } from '../lib/managedZev'
import { useTranslation } from 'react-i18next'
import { useToast } from '../lib/toast'
import type { ImportLog, ImportPreviewResult } from '../types/api'
import { PageSkeleton } from '../components/PageSkeleton'
import { BulkDeleteModal } from '../features/imports/BulkDeleteModal'
import { ImportHistoryTable } from '../features/imports/ImportHistoryTable'
import { ImportProtocolModal } from '../features/imports/ImportProtocolModal'
import { ImportWizardModal } from '../features/imports/ImportWizardModal'
import {
    MAX_UPLOAD_BYTES,
    csvConfigFor,
    isLegacyExcel,
    isValidDelimiter,
    isValidTimestampFormat,
    parsePositiveInt,
    previewStampsEqual,
    type CsvColumnMap,
    type CsvFormatProfile,
    type PreviewStamp,
} from '../features/imports/importUtils'
import { formatBytes } from '../lib/numbers'
import { copyToClipboard } from '../lib/clipboard'
import { downloadBlob } from '../lib/downloadBlob'

/**
 * Metering import wizard + history log.
 *
 * Phase-3 nav regroup: mounted as the "Import history" tab of the Metering
 * hub (`/metering/imports`, `tab="imports"`). `embedded` drops the page
 * header because the hub renders it; standalone alias renders keep it.
 */
export function ImportsPage({ embedded = false }: { embedded?: boolean }) {
    const queryClient = useQueryClient()
    const { pushToast } = useToast()
    const { dialog, confirm, handleConfirm, handleCancel, isLoading: dialogLoading } = useConfirmDialog()
    const { settings } = useAppSettings()
    const { selectedZevId, selectedZev } = useManagedZev()
    const { t } = useTranslation()

    const { data, isLoading, isError, error: logsError, refetch: refetchLogs } = useQuery({ queryKey: queryKeys.metering.importLogs(), queryFn: fetchImportLogs })
    const logsErrorDetail = (logsError as { response?: { data?: { error?: string; detail?: string } } } | null)?.response?.data
    const logsErrorMessage = logsErrorDetail?.error || logsErrorDetail?.detail || null

    const [wizardOpen, setWizardOpen] = useState(false)
    const [wizardStep, setWizardStep] = useState<1 | 2>(1)

    const [source, setSource] = useState<'csv' | 'sdatch'>('csv')
    const [file, setFile] = useState<File | null>(null)

    const [hasHeader, setHasHeader] = useState(true)
    const [delimiter, setDelimiter] = useState(',')
    const [formatProfile, setFormatProfile] = useState<CsvFormatProfile>('daily_15min')
    const [timestampFormat, setTimestampFormat] = useState('%d.%m.%Y')
    const [intervalMinutes, setIntervalMinutes] = useState('15')
    const [valuesCount, setValuesCount] = useState('96')
    const [overwriteExisting, setOverwriteExisting] = useState(false)
    const [columnMap, setColumnMap] = useState<CsvColumnMap>(() => csvConfigFor(true, 'daily_15min').columnMap)

    const [preview, setPreview] = useState<ImportPreviewResult | null>(null)
    const [previewStamp, setPreviewStamp] = useState<PreviewStamp | null>(null)
    const previewReqId = useRef(0)
    const [selectedLog, setSelectedLog] = useState<ImportLog | null>(null)
    const [showBulkDeleteModal, setShowBulkDeleteModal] = useState(false)
    const [bulkDeleteMode, setBulkDeleteMode] = useState<'period' | 'all'>('period')
    const [bulkDeleteFrom, setBulkDeleteFrom] = useState('')
    const [bulkDeleteTo, setBulkDeleteTo] = useState('')
    const [bulkDeleteArmed, setBulkDeleteArmed] = useState(false)

    const scopedZevId = selectedZevId
    const importLogs = useMemo(
        () => (data ?? []).filter((log) => !selectedZevId || log.zev === selectedZevId),
        [data, selectedZevId],
    )

    const currentStamp = useMemo<PreviewStamp | null>(() => {
        if (!file) return null
        return {
            fileName: file.name,
            fileSize: file.size,
            lastModified: file.lastModified,
            source,
            zevId: scopedZevId ?? '',
            hasHeader,
            delimiter,
            formatProfile,
            timestampFormat,
            intervalMinutes,
            valuesCount,
            overwriteExisting,
            columnMap,
        }
    }, [file, source, scopedZevId, hasHeader, delimiter, formatProfile, timestampFormat, intervalMinutes, valuesCount, overwriteExisting, columnMap])

    const previewStampMatches = previewStampsEqual(previewStamp, currentStamp)

    const fileError = !file
        ? null
        : isLegacyExcel(file.name)
            ? t('pages.imports.wizard.xlsRejected')
            : file.size > MAX_UPLOAD_BYTES
                ? t('pages.imports.wizard.fileTooLarge', { size: formatBytes(file.size), limit: formatBytes(MAX_UPLOAD_BYTES) })
                : null

    const parsedIntervalMinutes = parsePositiveInt(intervalMinutes)
    const parsedValuesCount = parsePositiveInt(valuesCount)
    // Bounds mirror the backend coercion in csv_importer.py.
    const intervalMinutesError = parsedIntervalMinutes === null || parsedIntervalMinutes < 1
        ? t('pages.imports.wizard.intervalMinutesInvalid')
        : null
    const valuesCountError = parsedValuesCount === null || parsedValuesCount < 1 || parsedValuesCount > 1440
        ? t('pages.imports.wizard.valuesCountInvalid')
        : null
    const delimiterError = !isValidDelimiter(delimiter)
        ? t('pages.imports.wizard.delimiterInvalid')
        : null
    // Client-side mirror of the backend full-date rule: a format without
    // year/month/day (e.g. "%d.%m") passes nothing — the server rejects it.
    // Day-of-year (%Y-%j) and week-based formats count as month+day.
    const timestampFormatError = !isValidTimestampFormat(timestampFormat)
        ? t('pages.imports.wizard.timestampFormatInvalid')
        : null
    const csvConfigErrors = [intervalMinutesError, valuesCountError, delimiterError, timestampFormatError].filter((entry) => entry !== null)
    const csvConfigValid = csvConfigErrors.length === 0

    const previewMutation = useMutation({
        mutationFn: previewCsvImport,
    })

    function describeUploadError(error: unknown, fallback?: string): string {
        const response = (error as { response?: { status?: number; data?: { error?: string; detail?: string } } })?.response
        if (response?.status === 413) return t('pages.imports.messages.importTooLarge', { limit: formatBytes(MAX_UPLOAD_BYTES) })
        if (response?.status === 429) return t('pages.imports.messages.importThrottled')
        // `detail` is the proxy's error shape (e.g. the nginx 413 body).
        const data = response?.data
        return data?.error || data?.detail || fallback || t('pages.imports.messages.importFailed')
    }

    const uploadMutation = useMutation({
        mutationFn: uploadMeteringFile,
        onSuccess: (result) => {
            const errorCount = result.errors?.length ?? 0
            const warnings = result.warnings ?? []
            resetWizard()
            void queryClient.invalidateQueries({ queryKey: ['metering'] })
            if (errorCount > 0) {
                setSelectedLog(result)
                pushToast(
                    t('pages.imports.messages.importSuccessWithIssues', {
                        imported: result.rows_imported,
                        skipped: result.rows_skipped,
                        count: errorCount,
                    }),
                    'error',
                )
            } else if (warnings.length > 0) {
                setSelectedLog(result)
                pushToast(
                    t('pages.imports.messages.importSuccessWithOverwrites', {
                        imported: result.rows_imported,
                        skipped: result.rows_skipped,
                        overwritten: result.rows_overwritten,
                    }),
                    'success',
                )
            } else {
                pushToast(t('pages.imports.messages.importSuccess', { imported: result.rows_imported, skipped: result.rows_skipped }), 'success')
            }
        },
        onError: (error) => {
            pushToast(describeUploadError(error), 'error')
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
                    count: result.deleted_logs,
                    logs: result.deleted_logs,
                    readings: result.deleted_readings,
                }),
                'success',
            )
            void queryClient.invalidateQueries({ queryKey: queryKeys.metering.importLogs() })
            void queryClient.invalidateQueries({ queryKey: ['metering'] })
        },
        onError: (error) => {
            const code = (error as { response?: { data?: { code?: string } } })?.response?.data?.code
            pushToast(t(code === 'overwrite_import_protected' ? 'pages.imports.delete.overwriteProtected' : 'pages.imports.messages.deleteFailed'), 'error')
        },
    })

    const bulkDeleteMutation = useMutation({
        mutationFn: bulkDeleteImportLogs,
        onSuccess: (result) => {
            setShowBulkDeleteModal(false)
            setBulkDeleteMode('period')
            setBulkDeleteFrom('')
            setBulkDeleteTo('')
            setBulkDeleteArmed(false)
            setSelectedLog(null)
            pushToast(
                t('pages.imports.messages.deleteSuccess', {
                    count: result.deleted_logs,
                    logs: result.deleted_logs,
                    readings: result.deleted_readings,
                }),
                'success',
            )
            void queryClient.invalidateQueries({ queryKey: queryKeys.metering.importLogs() })
            void queryClient.invalidateQueries({ queryKey: ['metering'] })
        },
        onError: (error) => {
            const code = (error as { response?: { data?: { code?: string } } })?.response?.data?.code
            pushToast(t(code === 'overwrite_import_protected' ? 'pages.imports.delete.overwriteProtected' : 'pages.imports.messages.deleteFailed'), 'error')
        },
    })

    const canGoStep2 = !!file && !fileError && !!scopedZevId
    const missingMeteringPoints = preview?.summary.missing_metering_points ?? 0
    const previewOutdated = !!preview && !previewStampMatches
    const hasPreviewErrors = (preview?.errors?.length ?? 0) > 0
    const canStartImport = source === 'csv'
        ? !!file && !fileError && !!preview && previewStampMatches && csvConfigValid && !hasPreviewErrors && missingMeteringPoints === 0 && !!scopedZevId
        : !!file && !fileError && !!scopedZevId

    const previewRows = preview?.preview_rows ?? []
    const [historyFilters, setHistoryFilters] = useState<ColumnFiltersState>([])
    const importLogRows = useMemo(
        () =>
            importLogs.map((log) => ({
                ...log,
                created_display: formatDateTime(log.created_at, settings),
                filename_display: log.filename || '-',
                rows_total_display: log.rows_total ?? '-',
                zev_display: log.zev_name || log.zev || '-',
                imported_by_display: log.imported_by_display || '-',
            })),
        [importLogs, settings],
    )

    const importLogColumns = useMemo<ColumnDef<(typeof importLogRows)[number], unknown>[]>(
        () => [
            {
                accessorKey: 'created_at',
                header: t('pages.imports.columns.created'),
                cell: (ctx) => ctx.row.original.created_display,
            },
            {
                accessorKey: 'source',
                header: t('pages.imports.columns.source'),
                filterFn: 'equalsString',
                cell: (ctx) => {
                    const raw = String(ctx.row.original.source ?? '').toLowerCase()
                    if (raw === 'csv') return t('pages.imports.format.csv')
                    if (raw === 'sdatch') return t('pages.imports.format.sdatch')
                    return ctx.row.original.source
                },
            },
            {
                accessorKey: 'zev_display',
                header: t('pages.imports.columns.zev'),
            },
            {
                accessorKey: 'imported_by_display',
                header: t('pages.imports.columns.importedBy'),
            },
            {
                accessorKey: 'filename',
                header: t('pages.imports.columns.filename'),
                cell: (ctx) => ctx.row.original.filename_display,
            },
            {
                accessorKey: 'rows_total',
                header: t('pages.imports.columns.total'),
                meta: { numeric: true },
                cell: (ctx) => ctx.row.original.rows_total_display,
            },
            {
                accessorKey: 'rows_imported',
                header: t('pages.imports.columns.imported'),
                meta: { numeric: true },
            },
            {
                accessorKey: 'rows_skipped',
                header: t('pages.imports.columns.skipped'),
                meta: { numeric: true },
            },
            {
                id: 'protocol',
                header: t('pages.imports.columns.protocol'),
                enableSorting: false,
                cell: (ctx) => (
                    <button type="button" className="button button-secondary button-compact" onClick={() => setSelectedLog(ctx.row.original)}>
                        <FontAwesomeIcon icon={faEye} fixedWidth />
                        {t('pages.imports.actions.openProtocol')}
                    </button>
                ),
            },
            {
                id: 'actions',
                header: t('pages.imports.columns.actions'),
                enableSorting: false,
                cell: (ctx) => (
                    <ActionMenu
                        label={t('pages.imports.actions.rowActions')}
                        items={[
                            {
                                key: 'delete',
                                label: t('pages.imports.actions.deleteImport'),
                                icon: <FontAwesomeIcon icon={faTrash} fixedWidth />,
                                danger: true,
                                disabled: deleteImportMutation.isPending || dialogLoading || ctx.row.original.rows_overwritten > 0,
                                onClick: () => confirm({
                                    title: t('pages.imports.delete.singleTitle'),
                                    message: t('pages.imports.delete.singleMessage', {
                                        filename: ctx.row.original.filename || '-',
                                        createdAt: formatDateTime(ctx.row.original.created_at, settings),
                                    }),
                                    confirmText: t('pages.imports.delete.confirmAction'),
                                    isDangerous: true,
                                    onConfirm: () => deleteImportMutation.mutate(ctx.row.original.id),
                                }),
                            },
                        ]}
                    />
                ),
            },
        ],
        [t, settings, confirm, deleteImportMutation, dialogLoading],
    )

    function resetWizard() {
        previewReqId.current += 1
        const cfg = csvConfigFor(true, 'daily_15min')
        setWizardOpen(false)
        setWizardStep(1)
        setSource('csv')
        setFile(null)
        setHasHeader(true)
        setDelimiter(cfg.delimiter)
        setFormatProfile('daily_15min')
        setTimestampFormat('%d.%m.%Y')
        setIntervalMinutes('15')
        setValuesCount('96')
        setOverwriteExisting(false)
        setColumnMap(cfg.columnMap)
        setPreview(null)
        setPreviewStamp(null)
    }

    function closeBulkDeleteModal() {
        setShowBulkDeleteModal(false)
        setBulkDeleteMode('period')
        setBulkDeleteFrom('')
        setBulkDeleteTo('')
        setBulkDeleteArmed(false)
    }

    function handleSourceChange(nextSource: 'csv' | 'sdatch') {
        setSource(nextSource)
        setFile(null)
        setPreview(null)
        setPreviewStamp(null)
        setWizardStep(1)
    }

    function handleFormatProfileChange(nextProfile: CsvFormatProfile) {
        setFormatProfile(nextProfile)
        const cfg = csvConfigFor(hasHeader, nextProfile)
        setDelimiter(cfg.delimiter)
        setColumnMap(cfg.columnMap)
        setPreview(null)
        setPreviewStamp(null)
    }

    function handleRemoveFile() {
        setFile(null)
        setPreview(null)
        setPreviewStamp(null)
    }

    function handleHasHeaderChange(nextHasHeader: boolean) {
        setHasHeader(nextHasHeader)
        const cfg = csvConfigFor(nextHasHeader, formatProfile)
        setDelimiter(cfg.delimiter)
        setColumnMap(cfg.columnMap)
    }

    function handleFileChange(event: React.ChangeEvent<HTMLInputElement>) {
        // File metadata is not an identity: a replacement can have the same
        // name, size and modification time but different contents.
        previewReqId.current += 1
        setPreview(null)
        setPreviewStamp(null)
        const picked = event.target.files?.[0] ?? null
        if (picked && isLegacyExcel(picked.name)) {
            event.target.value = ''
            setFile(null)
            pushToast(t('pages.imports.wizard.xlsRejected'), 'error')
            return
        }
        setFile(picked)
    }

    function handleNextStep(event: FormEvent<HTMLFormElement>) {
        event.preventDefault()
        if (!file || fileError) {
            pushToast(t('pages.imports.messages.chooseFileFirst'), 'error')
            return
        }
        if (!scopedZevId) {
            pushToast(t('pages.imports.messages.selectZevFirst'), 'error')
            return
        }
        setWizardStep(2)
    }

    function copyMissingMeterIds() {
        const ids = preview?.missing_meter_ids ?? []
        if (ids.length === 0) {
            pushToast(t('pages.imports.preview.copyMissingIdsFailed'), 'error')
            return
        }
        void copyToClipboard(ids.join('\n')).then((ok) => {
            if (ok) pushToast(t('pages.imports.preview.copiedMissingIds', { count: ids.length }), 'success')
            else pushToast(t('pages.imports.preview.copyMissingIdsFailed'), 'error')
        })
    }

    function downloadMissingMeterIds() {
        const ids = preview?.missing_meter_ids ?? []
        if (ids.length === 0) return
        downloadBlob(new Blob([ids.join('\n')], { type: 'text/plain' }), 'missing-meter-ids.txt')
    }

    function loadPreview() {
        if (!file || fileError) {
            pushToast(t('pages.imports.messages.chooseFileFirst'), 'error')
            return
        }
        if (!scopedZevId) {
            pushToast(t('pages.imports.messages.selectZevForCsv'), 'error')
            return
        }
        if (!csvConfigValid || parsedIntervalMinutes === null || parsedValuesCount === null) {
            pushToast(t('pages.imports.messages.fixConfigFirst'), 'error')
            return
        }
        const stamp = currentStamp!
        const reqId = ++previewReqId.current
        previewMutation.mutate(
            {
                file,
                zevId: scopedZevId,
                columnMap,
                hasHeader,
                delimiter,
                formatProfile,
                timestampFormat,
                intervalMinutes: parsedIntervalMinutes,
                valuesCount: parsedValuesCount,
                overwriteExisting,
            },
            {
                onSuccess: (result) => {
                    if (reqId !== previewReqId.current) return
                    setPreview(result)
                    setPreviewStamp(stamp)
                    if (result.errors.length > 0) {
                        pushToast(t('pages.imports.messages.previewLoadedWithIssues', { count: result.errors.length }), 'error')
                    } else {
                        pushToast(t('pages.imports.messages.previewLoaded'), 'success')
                    }
                },
                onError: (error) => {
                    if (reqId !== previewReqId.current) return
                    pushToast(describeUploadError(error, t('pages.imports.messages.previewFailed')), 'error')
                },
            },
        )
    }

    function startImport() {
        if (!file || fileError) {
            pushToast(t('pages.imports.messages.chooseFileFirst'), 'error')
            return
        }
        if (!scopedZevId) {
            pushToast(t(source === 'csv' ? 'pages.imports.messages.selectZevForCsv' : 'pages.imports.messages.selectZevForSdatch'), 'error')
            return
        }

        if (source === 'csv') {
            if (!preview || !previewStampMatches) {
                pushToast(t('pages.imports.messages.loadPreviewFirst'), 'error')
                return
            }
            if (hasPreviewErrors) {
                pushToast(t('pages.imports.messages.previewLoadedWithIssues', { count: preview.errors.length }), 'error')
                return
            }
            if (preview.summary.missing_metering_points > 0) {
                pushToast(t('pages.imports.messages.createMissingMetersFirst'), 'error')
                return
            }
            if (!csvConfigValid || parsedIntervalMinutes === null || parsedValuesCount === null) {
                pushToast(t('pages.imports.messages.fixConfigFirst'), 'error')
                return
            }
            const doUpload = () =>
                uploadMutation.mutate({
                    source,
                    zevId: scopedZevId,
                    file,
                    columnMap,
                    hasHeader,
                    delimiter,
                    formatProfile,
                    timestampFormat,
                    intervalMinutes: parsedIntervalMinutes,
                    valuesCount: parsedValuesCount,
                    overwriteExisting,
                })
            if (overwriteExisting) {
                const existingCount = preview?.summary.readings_existing ?? 0
                confirm({
                    title: t('pages.imports.wizard.overwriteConfirmTitle'),
                    message:
                        existingCount > 0
                            ? t('pages.imports.wizard.overwriteConfirmMessageWithCount', {
                                  zevName: selectedZev?.name ?? scopedZevId,
                                  filename: file.name,
                                  count: existingCount,
                              })
                            : t('pages.imports.wizard.overwriteConfirmMessage', {
                                  zevName: selectedZev?.name ?? scopedZevId,
                                  filename: file.name,
                              }),
                    confirmText: t('pages.imports.wizard.startImport'),
                    isDangerous: true,
                    onConfirm: doUpload,
                })
                return
            }
            doUpload()
            return
        }

        uploadMutation.mutate({ source, zevId: scopedZevId, file })
    }

    const bulkDeleteScopeLogs = useMemo(() => {
        if (bulkDeleteMode === 'all') return importLogs
        // Table search/filter never narrows deletion: the scope must come
        // from exactly the backend scope (ZEV + dates). Both sides compare
        // instants in the same half-open UTC range.
        if (!bulkDeleteFrom || !bulkDeleteTo) return []
        const start = new Date(`${bulkDeleteFrom}T00:00:00Z`).getTime()
        const end = new Date(`${bulkDeleteTo}T00:00:00Z`).getTime() + 24 * 60 * 60 * 1000
        return importLogs.filter((log) => {
            const createdAt = new Date(log.created_at).getTime()
            return createdAt >= start && createdAt < end
        })
    }, [bulkDeleteMode, bulkDeleteFrom, bulkDeleteTo, importLogs])

    const bulkDeleteVisibleCount = bulkDeleteScopeLogs.length

    // A protected log in scope rejects the entire bulk operation
    // server-side with zero deletions. Identify blockers up front (the
    // loaded logs are the exact backend scope) and prevent a predictably
    // rejected submission; the server stays authoritative.
    const bulkDeleteProtectedLogs = useMemo(
        () => bulkDeleteScopeLogs.filter((log) => (log.rows_overwritten ?? 0) > 0),
        [bulkDeleteScopeLogs],
    )
    const bulkDeleteProtectedExamples = useMemo(
        () =>
            bulkDeleteProtectedLogs.slice(0, 5).map(
                (log) => `${log.filename || '-'} — ${formatDateTime(log.created_at, settings)}`,
            ),
        [bulkDeleteProtectedLogs, settings],
    )

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

        setBulkDeleteArmed(true)
    }

    function confirmBulkDelete() {
        bulkDeleteMutation.mutate({
            mode: bulkDeleteMode,
            dateFrom: bulkDeleteMode === 'period' ? bulkDeleteFrom : undefined,
            dateTo: bulkDeleteMode === 'period' ? bulkDeleteTo : undefined,
            zevId: selectedZevId || undefined,
        })
    }

    if (isLoading)
        return embedded ? (
            <PageSkeleton variant="table" />
        ) : (
            <div className="page-stack">
                <header>
                    <h2>{t('pages.imports.title')}</h2>
                    <p className="muted">{t('pages.imports.description')}</p>
                </header>
                <PageSkeleton variant="table" />
            </div>
        )
    if (isError)
        return (
            <div className="card error-banner">
                <p style={{ margin: '0 0 0.75rem' }}>
                    {t('pages.imports.loadFailed')}
                    {logsErrorMessage ? ` — ${logsErrorMessage}` : ''}
                </p>
                <button className="button button-secondary" type="button" onClick={() => refetchLogs()}>
                    {t('common.retry')}
                </button>
            </div>
        )

    return (
        <div className="page-stack">
            {!embedded && (
                <header>
                    {selectedZev?.name ? <p className="eyebrow">{selectedZev.name}</p> : null}
                    <h2>{t('pages.imports.title')}</h2>
                    <p className="muted">{t('pages.imports.description')}</p>
                </header>
            )}

            <section className="card" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '1rem', flexWrap: 'wrap' }}>
                <div>
                    <h3 style={{ marginBottom: '0.3rem' }}>{t('pages.imports.startTitle')}</h3>
                    <p className="muted" style={{ margin: 0 }}>{t('pages.imports.startDescription')}</p>
                </div>
                <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
                    <button className="button button-primary" onClick={() => setWizardOpen(true)}>
                        <FontAwesomeIcon icon={faPlus} fixedWidth />
                        {t('pages.imports.actions.newImport')}
                    </button>
                    {importLogs.length > 0 && (
                        <button className="button button-danger" type="button" onClick={() => setShowBulkDeleteModal(true)}>
                            <FontAwesomeIcon icon={faTrash} fixedWidth />
                            {t('pages.imports.actions.deleteImports')}
                        </button>
                    )}
                </div>
            </section>

            {wizardOpen && (
                <ImportWizardModal
                step={wizardStep}
                source={source}
                file={file}
                fileError={fileError}
                hasHeader={hasHeader}
                delimiter={delimiter}
                delimiterError={delimiterError}
                formatProfile={formatProfile}
                timestampFormat={timestampFormat}
                timestampFormatError={timestampFormatError}
                intervalMinutes={intervalMinutes}
                intervalMinutesError={intervalMinutesError}
                valuesCount={valuesCount}
                valuesCountError={valuesCountError}
                overwriteExisting={overwriteExisting}
                columnMap={columnMap}
                preview={preview}
                previewOutdated={previewOutdated}
                previewLoading={previewMutation.isPending}
                missingMeteringPoints={missingMeteringPoints}
                previewRows={previewRows}
                scopedZevId={scopedZevId ?? ''}
                selectedZevName={selectedZev?.name ?? null}
                canGoStep2={canGoStep2}
                canStartImport={canStartImport}
                csvConfigValid={csvConfigValid}
                uploadPending={uploadMutation.isPending}
                onClose={resetWizard}
                onSourceChange={handleSourceChange}
                onFileChange={handleFileChange}
                onRemoveFile={handleRemoveFile}
                onHasHeaderChange={handleHasHeaderChange}
                onDelimiterChange={setDelimiter}
                onFormatProfileChange={handleFormatProfileChange}
                onTimestampFormatChange={setTimestampFormat}
                onIntervalMinutesChange={setIntervalMinutes}
                onValuesCountChange={setValuesCount}
                onColumnMapChange={(patch) => setColumnMap((prev) => ({ ...prev, ...patch }))}
                onOverwriteChange={setOverwriteExisting}
                onSubmitStep1={handleNextStep}
                onBackToStep1={() => setWizardStep(1)}
                onLoadPreview={loadPreview}
                onStartImport={startImport}
                onCopyMissingIds={copyMissingMeterIds}
                onDownloadMissingIds={downloadMissingMeterIds}
            />
            )}

            <ImportHistoryTable
                rows={importLogRows}
                columns={importLogColumns}
                getRowId={(row) => row.id}
                filters={historyFilters}
                onFiltersChange={setHistoryFilters}
                onNewImport={() => setWizardOpen(true)}
            />

            <BulkDeleteModal
                open={showBulkDeleteModal}
                mode={bulkDeleteMode}
                dateFrom={bulkDeleteFrom}
                dateTo={bulkDeleteTo}
                armed={bulkDeleteArmed}
                visibleCount={bulkDeleteVisibleCount}
                protectedCount={bulkDeleteProtectedLogs.length}
                protectedExamples={bulkDeleteProtectedExamples}
                pending={bulkDeleteMutation.isPending}
                zevName={selectedZev?.name ?? null}
                onClose={closeBulkDeleteModal}
                onModeChange={setBulkDeleteMode}
                onDateFromChange={setBulkDeleteFrom}
                onDateToChange={setBulkDeleteTo}
                onReview={submitBulkDelete}
                onBack={() => setBulkDeleteArmed(false)}
                onConfirm={confirmBulkDelete}
            />

            <ImportProtocolModal log={selectedLog} onClose={() => setSelectedLog(null)} />

            {dialog && (
                <ConfirmDialog {...dialog} isLoading={dialogLoading} onConfirm={handleConfirm} onCancel={handleCancel} />
            )}
        </div>
    )
}
