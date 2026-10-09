import { useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { importSupplementaryCsv } from '../../lib/api/supplementary'
import { formatApiError } from '../../lib/api/errors'
import { queryKeys } from '../../lib/api/queryKeys'
import { CSV_COLUMNS } from '../../lib/supplementary'
import { useToast } from '../../lib/toast'
import type { SupplementaryIngestResult } from '../../types/api'

const MAX_ERRORS_SHOWN = 5

/** Upload a CSV of quarter-hour values. Checked first (dry run), imported only when the whole file is valid. */
export function CsvImport({ sourceId }: { sourceId: string }) {
    const { t } = useTranslation()
    const { pushToast } = useToast()
    const queryClient = useQueryClient()
    const inputRef = useRef<HTMLInputElement>(null)
    const [file, setFile] = useState<File | null>(null)
    const [result, setResult] = useState<{ dryRun: boolean; data: SupplementaryIngestResult } | null>(null)
    const [error, setError] = useState<{ message: string; rejected: SupplementaryIngestResult['rejected'] } | null>(null)

    const run = useMutation({
        mutationFn: ({ dryRun }: { dryRun: boolean }) => importSupplementaryCsv(sourceId, file as File, { dryRun }),
        onMutate: () => {
            setError(null)
            setResult(null)
        },
        onSuccess: (data, { dryRun }) => {
            setResult({ dryRun, data })
            if (!dryRun) {
                setFile(null)
                if (inputRef.current) inputRef.current.value = ''
                void queryClient.invalidateQueries({ queryKey: queryKeys.metering.supplementarySources() })
                void queryClient.invalidateQueries({ queryKey: ['metering', 'dashboard-summary'] })
                pushToast(t('supplementary.csv.imported', { count: data.accepted }), 'success')
            }
        },
        onError: (err: any) => {
            const body = err?.response?.data
            setError({
                message: formatApiError(err, t('common.error')),
                rejected: Array.isArray(body?.rejected) ? body.rejected : [],
            })
        },
    })

    return (
        <div style={{ display: 'grid', gap: '0.5rem' }}>
            <strong>{t('supplementary.csv.title')}</strong>
            <small className="muted">{t('supplementary.csv.hint', { columns: CSV_COLUMNS.join(', ') })}</small>
            <input
                ref={inputRef}
                type="file"
                accept=".csv,text/csv"
                aria-label={t('supplementary.csv.file')}
                onChange={(event) => {
                    setFile(event.target.files?.[0] ?? null)
                    setResult(null)
                    setError(null)
                }}
            />
            <div className="actions-row actions-row-wrap">
                <button
                    type="button"
                    className="button button-secondary button-compact"
                    disabled={!file || run.isPending}
                    onClick={() => run.mutate({ dryRun: true })}
                >
                    {t('supplementary.csv.check')}
                </button>
                <button
                    type="button"
                    className="button button-primary button-compact"
                    disabled={!file || run.isPending}
                    onClick={() => run.mutate({ dryRun: false })}
                >
                    {run.isPending ? t('common.saving') : t('supplementary.csv.import')}
                </button>
            </div>
            {result && (
                <p role="status" className="muted" style={{ margin: 0 }}>
                    {t(result.dryRun ? 'supplementary.csv.checked' : 'supplementary.csv.result', {
                        accepted: result.data.accepted,
                        updated: result.data.updated,
                        dropped: result.data.dropped_outside_assignment,
                    })}
                </p>
            )}
            {error && (
                <div className="error-banner" role="alert">
                    <p style={{ margin: 0 }}>{error.message}</p>
                    {error.rejected.length > 0 && (
                        <ul style={{ margin: '0.5rem 0 0', paddingLeft: '1.25rem' }}>
                            {error.rejected.slice(0, MAX_ERRORS_SHOWN).map((row) => (
                                <li key={row.index}>{t('supplementary.csv.rowError', { row: row.index + 2, reason: row.reason })}</li>
                            ))}
                            {error.rejected.length > MAX_ERRORS_SHOWN && (
                                <li>{t('supplementary.csv.moreErrors', { count: error.rejected.length - MAX_ERRORS_SHOWN })}</li>
                            )}
                        </ul>
                    )}
                </div>
            )}
        </div>
    )
}
