import type { ExportJob } from '../../types/api'
import { api } from './client'

/** Request a whole-ZEV annual-statement ZIP; resolves with the queued job. */
export async function createAnnualStatementsExport(params: {
    year: number
    zev_id: string
}): Promise<ExportJob> {
    const { data } = await api.post<{ job: ExportJob }>('/exports/jobs/', {
        export_type: 'annual_statements',
        zev_id: params.zev_id,
        params: { year: params.year },
    })
    return data.job
}

/** The caller's own annual-statement export jobs for a ZEV, newest first. */
export async function fetchAnnualStatementExports(zevId: string): Promise<ExportJob[]> {
    const { data } = await api.get<ExportJob[]>('/exports/jobs/', {
        params: { export_type: 'annual_statements', zev_id: zevId },
    })
    return data
}

/** Poll one job's progress and download availability. */
export async function fetchExportJob(jobId: string): Promise<ExportJob> {
    const { data } = await api.get<ExportJob>(`/exports/jobs/${jobId}/`)
    return data
}

/** Download the completed artifact as a blob. */
export async function downloadAnnualStatementsExport(jobId: string): Promise<Blob> {
    const { data } = await api.get(`/exports/jobs/${jobId}/download/`, {
        responseType: 'blob',
    })
    return data as Blob
}
