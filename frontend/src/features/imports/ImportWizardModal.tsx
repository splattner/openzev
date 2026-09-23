import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import {
    faArrowLeft,
    faArrowRight,
    faMagnifyingGlass,
    faUpload,
    faXmark,
} from '@fortawesome/free-solid-svg-icons'
import { useEffect, useRef } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { FormModal } from '../../components/FormModal'
import { MAX_UPLOAD_BYTES, type CsvColumnMap, type CsvFormatProfile, type FilePreview } from './importUtils'
import { formatBytes } from '../../lib/numbers'

/**
 * Where a previewed row's readings will land. A row can carry both directions
 * when a bidirectional meter's values are split by sign, so this renders a
 * list rather than a single value.
 */
function formatDirections(directions: string[] | undefined, t: (key: string) => string): string {
    if (!directions || directions.length === 0) return '-'
    return directions
        .map((direction) =>
            direction === 'out'
                ? t('pages.imports.preview.directionOut')
                : t('pages.imports.preview.directionIn'),
        )
        .join(', ')
}

function Badge({ label, ok }: { label: string; ok: boolean }) {
    return (
        <span className={`badge ${ok ? 'badge-success' : 'badge-danger'}`}>
            {label}
        </span>
    )
}

export type ImportSource = 'csv' | 'sdatch'
export type FormatProfile = CsvFormatProfile

export interface ImportWizardModalProps {
    step: 1 | 2
    source: ImportSource
    files: File[]
    /** One entry per file, aligned with `files`; null when the file is fine. */
    fileErrors: Array<string | null>
    hasHeader: boolean
    delimiter: string
    delimiterError: string | null
    formatProfile: FormatProfile
    timestampFormat: string
    timestampFormatError: string | null
    intervalMinutes: string
    intervalMinutesError: string | null
    valuesCount: string
    valuesCountError: string | null
    overwriteExisting: boolean
    columnMap: CsvColumnMap
    previews: FilePreview[]
    /** Meter ids missing across all previewed files. */
    missingMeterIds: string[]
    previewOutdated: boolean
    previewLoading: boolean
    missingMeteringPoints: number
    scopedZevId: string
    selectedZevName: string | null
    canGoStep2: boolean
    canStartImport: boolean
    csvConfigValid: boolean
    uploadPending: boolean
    onClose: () => void
    onSourceChange: (source: ImportSource) => void
    onFileChange: (event: React.ChangeEvent<HTMLInputElement>) => void
    onRemoveFile: (index: number) => void
    onHasHeaderChange: (value: boolean) => void
    onDelimiterChange: (value: string) => void
    onFormatProfileChange: (profile: FormatProfile) => void
    onTimestampFormatChange: (value: string) => void
    onIntervalMinutesChange: (value: string) => void
    onValuesCountChange: (value: string) => void
    onColumnMapChange: (patch: Partial<CsvColumnMap>) => void
    onOverwriteChange: (value: boolean) => void
    onSubmitStep1: (event: React.FormEvent<HTMLFormElement>) => void
    onBackToStep1: () => void
    onLoadPreview: () => void
    onStartImport: () => void
    onCopyMissingIds: () => void
    onDownloadMissingIds: () => void
}

function FilePreviewBlock({ entry, heading }: { entry: FilePreview; heading: boolean }) {
    const { t } = useTranslation()
    const { preview } = entry
    const rows = preview?.preview_rows ?? []
    return (
        <div className="page-stack" style={{ gap: '0.5rem' }}>
            {heading && <strong>{entry.fileName}</strong>}
            {entry.error && (
                <div className="error-banner">{entry.error}</div>
            )}
            {preview && (
                <>
                    <div className="actions-row actions-row-wrap">
                        <Badge label={t('pages.imports.previewFound', { count: preview.summary.existing_metering_points })} ok={preview.summary.existing_metering_points > 0} />
                        <Badge label={t('pages.imports.previewMissing', { count: preview.summary.missing_metering_points })} ok={preview.summary.missing_metering_points === 0} />
                    </div>

                    {preview.summary.rows_skipped_existing > 0 && (
                        <p className="warning-banner">
                            {t('pages.imports.preview.existingRowsSkipped', { count: preview.summary.rows_skipped_existing })}
                        </p>
                    )}

                    {preview.errors.length > 0 && (
                        <div className="error-banner">
                            <ul style={{ margin: 0, paddingLeft: '1.1rem' }}>
                                {preview.errors.slice(0, 8).map((error, index) => (
                                    <li key={`${error.row ?? 'general'}-${index}`}>
                                        {error.row ? <>{t('pages.imports.preview.rowPrefix', { row: error.row })} </> : ''}{error.error}
                                    </li>
                                ))}
                            </ul>
                        </div>
                    )}

                    {rows.length > 0 && (
                        <div style={{ maxHeight: 250, overflow: 'auto', border: '1px solid var(--border-default)', borderRadius: 6 }}>
                            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                                <thead>
                                    <tr>
                                        <th style={{ textAlign: 'left', padding: '0.4rem 0.6rem' }}>{t('pages.imports.preview.row')}</th>
                                        <th style={{ textAlign: 'left', padding: '0.4rem 0.6rem' }}>{t('pages.imports.preview.meterId')}</th>
                                        <th style={{ textAlign: 'left', padding: '0.4rem 0.6rem' }}>{t('pages.imports.preview.status')}</th>
                                        <th style={{ textAlign: 'left', padding: '0.4rem 0.6rem' }}>{t('pages.imports.preview.timestamp')}</th>
                                        <th style={{ textAlign: 'left', padding: '0.4rem 0.6rem' }}>{t('pages.imports.preview.direction')}</th>
                                        <th style={{ textAlign: 'left', padding: '0.4rem 0.6rem' }}>{t('pages.imports.preview.existingData')}</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {rows.map((row) => (
                                        <tr key={`${row.row}-${row.meter_id ?? 'empty'}`} style={{ borderTop: '1px solid var(--border-default)' }}>
                                            <td style={{ padding: '0.4rem 0.6rem' }}>{row.row}</td>
                                            <td style={{ padding: '0.4rem 0.6rem' }}>{row.meter_id ?? '-'}</td>
                                            <td style={{ padding: '0.4rem 0.6rem' }}>
                                                <Badge label={row.metering_point_exists ? t('pages.imports.preview.exists') : t('pages.imports.preview.missing')} ok={row.metering_point_exists} />
                                            </td>
                                            <td style={{ padding: '0.4rem 0.6rem' }}>{row.timestamp ?? '-'}</td>
                                            <td style={{ padding: '0.4rem 0.6rem' }}>{formatDirections(row.directions, t)}</td>
                                            <td style={{ padding: '0.4rem 0.6rem' }}>
                                                {row.existing_data == null ? '-' : row.existing_data ? t('pages.imports.preview.yes') : t('pages.imports.preview.no')}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </>
            )}
        </div>
    )
}

export function ImportWizardModal(props: ImportWizardModalProps) {
    const { t } = useTranslation()
    const fileInputRef = useRef<HTMLInputElement>(null)
    // The native file input keeps its value after removal: clear it so
    // picking the same files again fires a change event.
    useEffect(() => {
        if (props.files.length === 0 && fileInputRef.current) {
            fileInputRef.current.value = ''
        }
    }, [props.files])
    const {
        step, source, files, fileErrors, hasHeader, delimiter, delimiterError,
        formatProfile, timestampFormat, timestampFormatError, intervalMinutes,
        intervalMinutesError, valuesCount, valuesCountError, overwriteExisting,
        columnMap, previews, missingMeterIds, previewOutdated, previewLoading, missingMeteringPoints,
        scopedZevId, selectedZevName, canGoStep2, canStartImport,
        csvConfigValid, uploadPending,
    } = props

    const showPreview = previews.length > 0 && !previewOutdated

    return (
        <FormModal isOpen={true} title={t('pages.imports.wizard.title')} onClose={props.onClose} maxWidth="1080px">
            <div className="page-stack" style={{ gap: '0.75rem' }}>
                <div className="muted" style={{ fontSize: '0.9rem' }}>
                    {t('pages.imports.wizard.step', { step })}
                </div>

                {step === 1 && (
                    <form onSubmit={props.onSubmitStep1} className="page-stack" style={{ gap: '0.75rem' }}>
                        <label>
                            <span>{t('pages.imports.wizard.sourceFormat')}</span>
                            <select value={source} onChange={(event) => props.onSourceChange(event.target.value as ImportSource)}>
                                <option value="csv">{t('pages.imports.format.csv')}</option>
                                <option value="sdatch">{t('pages.imports.format.sdatch')}</option>
                            </select>
                        </label>

                        <label>
                            <span>{t('pages.imports.wizard.sourceFile')}</span>
                            <input
                                ref={fileInputRef}
                                type="file"
                                multiple
                                onChange={props.onFileChange}
                                accept={source === 'csv' ? '.csv,.xlsx' : '.xml'}
                            />
                        </label>
                        <p className="muted" style={{ margin: 0, fontSize: '0.85rem' }}>
                            {t('pages.imports.wizard.supportedExtensions', {
                                extensions: source === 'csv' ? '.csv, .xlsx' : '.xml',
                            })}{' '}
                            {t('pages.imports.wizard.sizeLimit', { limit: formatBytes(MAX_UPLOAD_BYTES) })}
                        </p>
                        {source === 'csv' && (
                            <p className="muted" style={{ margin: 0, fontSize: '0.85rem' }}>
                                {t('pages.imports.wizard.sampleFiles')}{' '}
                                <a href="/samples/standard-readings.csv" download>{t('pages.imports.wizard.sampleStandard')}</a>
                                {' | '}
                                <a href="/samples/daily-15min-profile.csv" download>{t('pages.imports.wizard.sampleDaily')}</a>
                            </p>
                        )}
                        {files.map((file, index) => (
                            <div key={`${file.name}-${file.size}-${file.lastModified}-${index}`} className="card" style={{ padding: '0.6rem 0.8rem' }}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '0.6rem', flexWrap: 'wrap' }}>
                                    <div>
                                        <div><strong>{file.name}</strong></div>
                                        <div className="muted" style={{ fontSize: '0.85rem' }}>
                                            {formatBytes(file.size)} · {source === 'csv' ? t('pages.imports.format.csv') : t('pages.imports.format.sdatch')}
                                        </div>
                                    </div>
                                    <button type="button" className="button button-secondary" onClick={() => props.onRemoveFile(index)}>
                                        <FontAwesomeIcon icon={faXmark} fixedWidth />
                                        {t('pages.imports.wizard.removeFile')}
                                    </button>
                                </div>
                                {fileErrors[index] && (
                                    <p className="field-error" style={{ margin: '0.4rem 0 0' }}>
                                        {fileErrors[index]}
                                    </p>
                                )}
                            </div>
                        ))}
                        {files.length > 1 && (
                            <p className="muted" style={{ margin: 0, fontSize: '0.85rem' }}>
                                {t('pages.imports.wizard.sameSettingsHint', { count: files.length })}
                            </p>
                        )}

                        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.6rem' }}>
                            <button type="button" className="button button-secondary" onClick={props.onClose}>
                                <FontAwesomeIcon icon={faXmark} fixedWidth />
                                {t('pages.imports.wizard.cancel')}
                            </button>
                            <button type="submit" className="button button-primary" disabled={!canGoStep2}>
                                <FontAwesomeIcon icon={faArrowRight} fixedWidth />
                                {t('pages.imports.wizard.nextConfig')}
                            </button>
                        </div>
                        {!scopedZevId && (
                            <p className="muted" style={{ margin: 0, color: 'var(--danger-600)' }}>
                                {t('pages.imports.messages.selectZevFirst')}
                            </p>
                        )}
                    </form>
                )}

                {step === 2 && (
                    <div className="page-stack" style={{ gap: '0.75rem' }}>
                        {source === 'csv' ? (
                            <>
                                <label>
                                    <span>{t('pages.imports.wizard.selectZev')}</span>
                                    <input value={selectedZevName ?? t('pages.imports.wizard.noZevSelected')} disabled />
                                </label>
                                {!scopedZevId && (
                                    <p className="muted" style={{ margin: 0, color: 'var(--danger-600)' }}>{t('pages.imports.messages.selectZevFirst')}</p>
                                )}
                                <div className="inline-form grid grid-4">
                                    <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginTop: '1.6rem' }}>
                                        <input
                                            type="checkbox"
                                            checked={hasHeader}
                                            onChange={(event) => props.onHasHeaderChange(event.target.checked)}
                                        />
                                        <span>{t('pages.imports.wizard.hasHeader')}</span>
                                    </label>
                                    <label>
                                        <span>{t('pages.imports.wizard.delimiter')}</span>
                                        <input value={delimiter} onChange={(event) => props.onDelimiterChange(event.target.value)} placeholder="," />
                                        {delimiterError && (
                                            <span className="field-error">{delimiterError}</span>
                                        )}
                                    </label>
                                    <label>
                                        <span>{t('pages.imports.wizard.rowFormat')}</span>
                                        <select
                                            value={formatProfile}
                                            onChange={(event) => props.onFormatProfileChange(event.target.value as FormatProfile)}
                                        >
                                            <option value="standard">{t('pages.imports.rowFormat.standard')}</option>
                                            <option value="daily_15min">{t('pages.imports.rowFormat.daily15min')}</option>
                                        </select>
                                    </label>
                                    <label>
                                        <span>{t('pages.imports.wizard.datetimeFormat')}</span>
                                        <input
                                            value={timestampFormat}
                                            onChange={(event) => props.onTimestampFormatChange(event.target.value)}
                                            placeholder="%d.%m.%Y"
                                        />
                                        {timestampFormatError && (
                                            <span className="field-error">{timestampFormatError}</span>
                                        )}
                                    </label>
                                </div>

                                <div className="inline-form grid grid-4">
                                    <label>
                                        <span>{t('pages.imports.wizard.meterIdCol')}</span>
                                        <input
                                            value={columnMap.meter_id}
                                            onChange={(event) => props.onColumnMapChange({ meter_id: event.target.value })}
                                            placeholder={hasHeader ? 'meter_id' : '0'}
                                        />
                                    </label>
                                    <label>
                                        <span>{formatProfile === 'daily_15min' ? t('pages.imports.wizard.dateCol') : t('pages.imports.wizard.timestampCol')}</span>
                                        <input
                                            value={columnMap.timestamp}
                                            onChange={(event) => props.onColumnMapChange({ timestamp: event.target.value })}
                                            placeholder={hasHeader ? 'timestamp' : '3'}
                                        />
                                    </label>

                                    {formatProfile === 'standard' ? (
                                        <>
                                            <label>
                                                <span>{t('pages.imports.wizard.energyCol')}</span>
                                                <input
                                                    value={columnMap.energy_kwh}
                                                    onChange={(event) => props.onColumnMapChange({ energy_kwh: event.target.value })}
                                                    placeholder={hasHeader ? 'energy_kwh' : '4'}
                                                />
                                            </label>
                                        </>
                                    ) : (
                                        <>
                                            <label>
                                                <span>{t('pages.imports.wizard.firstIntervalCol')}</span>
                                                <input
                                                    value={columnMap.energy_start}
                                                    onChange={(event) => props.onColumnMapChange({ energy_start: event.target.value })}
                                                    placeholder={hasHeader ? 'energy_start' : '4'}
                                                />
                                            </label>
                                            <label>
                                                <span>{t('pages.imports.wizard.intervalsPerRow')}</span>
                                                <input type="number" min={1} max={1440} value={valuesCount} onChange={(event) => props.onValuesCountChange(event.target.value)} />
                                                {valuesCountError && (
                                                    <span className="field-error">{valuesCountError}</span>
                                                )}
                                            </label>
                                            <label>
                                                <span>{t('pages.imports.wizard.minutesPerInterval')}</span>
                                                <input type="number" min={1} value={intervalMinutes} onChange={(event) => props.onIntervalMinutesChange(event.target.value)} />
                                                {intervalMinutesError && (
                                                    <span className="field-error">{intervalMinutesError}</span>
                                                )}
                                            </label>
                                        </>
                                    )}
                                    <label>
                                        <span>{t('pages.imports.wizard.directionCol')}</span>
                                        {/* No placeholder: the other column
                                            fields carry real defaults, so a
                                            greyed-out sample here reads as a
                                            value that is already set — an
                                            empty direction column silently
                                            falls back to meter-type
                                            inference. The hint below says
                                            what belongs in the field. */}
                                        <input
                                            value={columnMap.direction}
                                            onChange={(event) => props.onColumnMapChange({ direction: event.target.value })}
                                        />
                                        <small className="muted">{t('pages.imports.wizard.directionColHint')}</small>
                                    </label>
                                </div>

                                <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                    <input
                                        type="checkbox"
                                        checked={overwriteExisting}
                                        onChange={(event) => props.onOverwriteChange(event.target.checked)}
                                    />
                                    <span>{t('pages.imports.wizard.overwriteExisting')}</span>
                                </label>

                                <div className="actions-row actions-row-wrap">
                                    <button
                                        type="button"
                                        className="button button-primary"
                                        onClick={props.onLoadPreview}
                                            disabled={previewLoading || files.length === 0 || fileErrors.some((entry) => entry !== null) || !scopedZevId || !csvConfigValid}
                                    >
                                        <FontAwesomeIcon icon={faMagnifyingGlass} fixedWidth />
                                        {previewLoading ? t('pages.imports.loadingPreview') : t('pages.imports.loadPreview')}
                                    </button>
                                </div>

                                {previewOutdated && (
                                    <div className="error-banner" style={{ marginTop: '0.4rem' }}>
                                        {t('pages.imports.messages.previewOutdated')}
                                    </div>
                                )}

                                {showPreview && missingMeteringPoints > 0 && (
                                    <div className="error-banner" style={{ marginTop: '0.4rem' }}>
                                        <div>{t('pages.imports.previewMissingBanner', { count: missingMeteringPoints })}</div>
                                        {missingMeterIds.length > 0 && (
                                            <div style={{ marginTop: '0.4rem', fontSize: '0.85rem' }}>
                                                <strong>{t('pages.imports.preview.missingIdsLabel')}</strong>{' '}
                                                {missingMeterIds.join(', ')}
                                                {missingMeteringPoints > missingMeterIds.length && (
                                                    <span> {t('pages.imports.preview.andMore', { count: missingMeteringPoints - missingMeterIds.length })}</span>
                                                )}
                                            </div>
                                        )}
                                        <div className="actions-row actions-row-wrap" style={{ marginTop: '0.5rem' }}>
                                            <button type="button" className="button button-secondary" onClick={props.onCopyMissingIds}>
                                                {t('pages.imports.preview.copyMissingIds')}
                                            </button>
                                            <button type="button" className="button button-secondary" onClick={props.onDownloadMissingIds}>
                                                {t('pages.imports.preview.downloadMissingIds')}
                                            </button>
                                            <Link to="/metering/points" className="button button-secondary">
                                                {t('pages.imports.preview.createMetersCta')}
                                            </Link>
                                        </div>
                                    </div>
                                )}

                                {showPreview && previews.map((entry, index) => (
                                    <FilePreviewBlock key={`${entry.fileName}-${index}`} entry={entry} heading={previews.length > 1} />
                                ))}
                            </>
                        ) : (
                            <>
                                <p className="muted" style={{ margin: 0 }}>
                                    {t('pages.imports.sdatchScope')}
                                </p>
                                <p className="muted" style={{ margin: 0 }}>
                                    {t('pages.imports.sdatchNoPreview')}
                                </p>
                                <label>
                                    <span>{t('pages.imports.wizard.selectZev')}</span>
                                    <input value={selectedZevName ?? t('pages.imports.wizard.noZevSelected')} disabled />
                                </label>
                                {!scopedZevId && (
                                    <p className="muted" style={{ margin: 0, color: 'var(--danger-600)' }}>{t('pages.imports.messages.selectZevFirst')}</p>
                                )}
                            </>
                        )}

                        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.6rem', marginTop: '0.4rem' }}>
                            <button type="button" className="button button-secondary" onClick={props.onBackToStep1}>
                                <FontAwesomeIcon icon={faArrowLeft} fixedWidth />
                                {t('pages.imports.wizard.back')}
                            </button>
                            <button type="button" className="button button-primary" onClick={props.onStartImport} disabled={uploadPending || !canStartImport}>
                                <FontAwesomeIcon icon={faUpload} fixedWidth />
                                {uploadPending ? t('pages.imports.wizard.importing') : t('pages.imports.wizard.startImport')}
                            </button>
                        </div>
                    </div>
                )}
            </div>
        </FormModal>
    )
}
