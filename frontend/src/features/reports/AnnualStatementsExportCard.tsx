import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { faDownload } from '@fortawesome/free-solid-svg-icons'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import type { ExportJob } from '../../types/api'
import { downloadBlob } from '../../lib/downloadBlob'
import {
    createAnnualStatementsExport,
    downloadAnnualStatementsExport,
    fetchAnnualStatementExports,
    fetchExportJob,
} from '../../lib/api/exports'

const POLL_INTERVAL_MS = 2500
// Consecutive failed polls before the card gives up (~5 × 2.5 s of outage).
const MAX_CONSECUTIVE_POLL_ERRORS = 5
// Wall-clock backstop against a server that keeps answering without ever
// finishing.
const MAX_POLL_DURATION_MS = 60 * 60 * 1000

const LATEST_KEY = (zevId: string, year: number) =>
    ['annualStatementExport', 'latest', zevId, year] as const

type AnnualStatementsExportCardProps = {
    zevId: string
    year: number
    enabled: boolean
    onBusyChange?: (busy: boolean) => void
}

export function AnnualStatementsExportCard({
    zevId,
    year,
    enabled,
    onBusyChange,
}: AnnualStatementsExportCardProps) {
    const { t } = useTranslation()
    const queryClient = useQueryClient()

    // The job the card currently shows.
    const [job, setJob] = useState<ExportJob | null>(null)
    const [actionFailed, setActionFailed] = useState(false)
    const [starting, setStarting] = useState(false)
    // Ref keyed by job id: the poll effect re-runs on every poll response
    // (each is a fresh ``job`` object), so a ``startedAt`` captured in the
    // effect body would reset every tick and the cap could never fire.
    const pollSessionRef = useRef<{ id: string; startedAt: number; errors: number } | null>(null)
    // The selection the card last presented. A create response that resolves
    // after the user switched ZEV/year belongs to the old selection and must
    // not be applied to the new one.
    const selectionRef = useRef({ zevId, year, enabled })
    const isCurrentSelection = (selection: { zevId: string; year: number; enabled: boolean }) =>
        selectionRef.current.zevId === selection.zevId &&
        selectionRef.current.year === selection.year &&
        selectionRef.current.enabled === selection.enabled

    useEffect(() => {
        setJob(null)
        setActionFailed(false)
        setStarting(false)
        pollSessionRef.current = null
        selectionRef.current = { zevId, year, enabled }
    }, [zevId, year, enabled])

    const latestQuery = useQuery({
        queryKey: LATEST_KEY(zevId, year),
        queryFn: async () => {
            if (!enabled || !zevId) return null
            const jobs = await fetchAnnualStatementExports(zevId)
            return jobs.find((candidate) => candidate.params?.year === year) ?? null
        },
        enabled: enabled && !!zevId,
        staleTime: Infinity,
    })

    // Seed from the newest matching job so a reload restores an in-flight or
    // completed export; skip when the user started one this session.
    useEffect(() => {
        if (!enabled || job || !latestQuery.data) return
        setJob(latestQuery.data)
    }, [enabled, job, latestQuery.data])

    const isPreparing = job !== null && (job.status === 'queued' || job.status === 'running')

    useEffect(() => {
        onBusyChange?.(isPreparing)
    }, [isPreparing, onBusyChange])

    useEffect(() => {
        if (!enabled || !job || !isPreparing) return
        const polledJobId = job.id
        let session = pollSessionRef.current
        if (!session || session.id !== polledJobId) {
            session = { id: polledJobId, startedAt: Date.now(), errors: 0 }
            pollSessionRef.current = session
        }
        const timer = window.setInterval(async () => {
            const current = pollSessionRef.current
            if (!current || current.id !== polledJobId) return
            if (Date.now() - current.startedAt > MAX_POLL_DURATION_MS) {
                setJob((old) =>
                    old && old.id === polledJobId ? { ...old, status: 'failed' } : old,
                )
                return
            }
            try {
                const updated = await fetchExportJob(polledJobId)
                if (pollSessionRef.current !== current) return
                current.errors = 0
                setJob(updated)
            } catch {
                if (pollSessionRef.current !== current) return
                // A transient blip must not end the poll: only repeated
                // failures (backend unreachable) mark the job failed.
                current.errors += 1
                if (current.errors >= MAX_CONSECUTIVE_POLL_ERRORS) {
                    window.clearInterval(timer)
                    setJob((old) =>
                        old && old.id === polledJobId ? { ...old, status: 'failed' } : old,
                    )
                }
            }
        }, POLL_INTERVAL_MS)
        return () => window.clearInterval(timer)
    }, [enabled, job, isPreparing])

    const prepare = async () => {
        setActionFailed(false)
        setStarting(true)
        const selection = selectionRef.current
        try {
            const created = await createAnnualStatementsExport({ zev_id: zevId, year })
            // A create can outlive the selection that started it; once the
            // user switched ZEV/year the response must not surface the old
            // ZEV's export under the new selection.
            if (!isCurrentSelection(selection)) return
            setJob(created)
            queryClient.invalidateQueries({ queryKey: LATEST_KEY(zevId, year) })
        } catch {
            if (isCurrentSelection(selection)) setActionFailed(true)
        } finally {
            if (isCurrentSelection(selection)) setStarting(false)
        }
    }

    const download = async (completedJob: ExportJob) => {
        setActionFailed(false)
        try {
            const blob = await downloadAnnualStatementsExport(completedJob.id)
            downloadBlob(blob, `annual-statements-${year}.zip`)
        } catch {
            // A download can fail after the card showed it as ready (e.g. the
            // link expired between the last poll and the click).
            setActionFailed(true)
        }
    }

    const showInitialBusy = !job && latestQuery.isLoading

    return (
        <section className="card">
            <h3 style={{ marginTop: 0 }}>{t('pages.reports.annualStatement.title')}</h3>
            <p className="muted" style={{ marginBottom: '1rem' }}>
                {t('pages.reports.annualStatement.ownerDescription')}
            </p>

            {actionFailed || (job && job.status === 'failed') ? (
                <p className="error-text" role="alert" style={{ marginTop: '0.5rem' }}>
                    {job && job.status === 'failed' && job.error_message
                        ? job.error_message
                        : t('pages.reports.annualStatement.error')}
                </p>
            ) : null}
            {job && job.status === 'completed' && job.expired ? (
                <p className="muted" role="status" style={{ marginTop: '0.5rem' }}>
                    {t('pages.reports.annualStatement.expired')}
                </p>
            ) : null}
            {job && job.status === 'completed' && !job.expired && (job.omitted_count ?? 0) > 0 ? (
                <p className="error-text" role="alert" style={{ marginTop: '0.5rem' }}>
                    {t('pages.reports.annualStatement.partialWarning', {
                        omitted: job.omitted_count,
                        total: (job.generated_count ?? 0) + (job.omitted_count ?? 0),
                    })}
                </p>
            ) : null}

            <div className="actions-row">
                {job && job.status === 'completed' && !job.expired ? (
                    <>
                        <button
                            type="button"
                            className="button button-primary"
                            onClick={() => download(job)}
                        >
                            <FontAwesomeIcon icon={faDownload} fixedWidth />
                            {t('pages.reports.annualStatement.downloadAll')}
                        </button>
                        <button type="button" className="button" disabled={starting} onClick={prepare}>
                            {t('pages.reports.annualStatement.prepareAgain')}
                        </button>
                    </>
                ) : (
                    <button
                        type="button"
                        className="button button-primary"
                        disabled={starting || isPreparing || showInitialBusy}
                        onClick={prepare}
                    >
                        <FontAwesomeIcon icon={faDownload} fixedWidth />
                        {isPreparing || starting
                            ? t('pages.reports.annualStatement.preparing')
                            : t('pages.reports.annualStatement.prepare')}
                    </button>
                )}
            </div>
        </section>
    )
}
