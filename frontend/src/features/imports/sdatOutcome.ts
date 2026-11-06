import type { BatchFileOutcome } from '../../lib/api/metering'
import type { ImportLog, SdatIssue } from '../../types/api'

/** File picker filter for SDAT-CH deliveries: plain XML or gzipped XML. */
export const SDAT_UPLOAD_ACCEPT = '.xml,.xml.gz,.gz'

export type DeletionProtection = 'overwrite_import_protected' | 'quarantine_replace_protected'

/** Deletion protection is calculated by the server for every stored log. */
export function importLogProtectionCode(
    log: Pick<ImportLog, 'deletion_protection_code'>,
): DeletionProtection | null {
    return log.deletion_protection_code ?? null
}

export function isImportLogDeletable(log: Pick<ImportLog, 'deletable'>): boolean {
    return log.deletable !== false
}

/** Whether the log carries the structured SDAT-CH outcome (blank for CSV/manual). */
export function isSdatLog(log: Pick<ImportLog, 'result_status'>): boolean {
    return !!log.result_status
}

/**
 * Machine-readable outcome of an SDAT-CH file, derived from `result_status`
 * and `result_counts` only — never from English warning prose.
 *
 * - `rejected`: the file wrote no observations (atomic rejection).
 * - `held`: only quarantine (non-billable) observations were written.
 * - `unchanged`: valid file, nothing changed (replay/duplicate/stale).
 * - `correctionOnly`: billable writes committed, but only overwrites — a
 *   successful correction with zero new billable rows.
 * - `accepted`: billable writes committed, including new rows.
 * - `legacy`: CSV/manual or pre-structured logs without the new metadata.
 */
export type SdatOutcomeKind = 'rejected' | 'held' | 'unchanged' | 'correctionOnly' | 'accepted' | 'legacy'

export function sdatOutcomeKind(
    log: Pick<ImportLog, 'result_status' | 'result_counts'>,
): SdatOutcomeKind {
    const status = log.result_status
    if (!status) return 'legacy'
    if (status !== 'accepted') return status
    const counts = log.result_counts
    if (counts && (counts.created ?? 0) === 0 && (counts.overwritten ?? 0) > 0) return 'correctionOnly'
    return 'accepted'
}

/** Rejected files return HTTP 201 with a log, but must remain selected for retry. */
export function isFailedBatchOutcome(outcome: BatchFileOutcome<ImportLog>): boolean {
    if (outcome.value === null) return true
    return outcome.value.result_status === 'rejected'
}

/** Ordered observation accounting for the protocol: promotion is a subset of
 * created/overwritten, never added on top (spec §4.2). */
export const SDAT_COUNT_ORDER = [
    'created',
    'overwritten',
    'held',
    'promoted',
    'duplicate',
    'original_existing',
    'stale',
    'excluded',
    'rejected',
    'quarantine_overwritten',
] as const

/** Structured issue params rendered as resolution details, in display order.
 * Values come from stable backend fields — never parsed from prose. */
export const SDAT_ISSUE_PARAM_ORDER = [
    'meter_id',
    'meter_type',
    'block_id',
    'other_block_id',
    'element',
    'document_type',
    'status',
    'creation',
    'root_element',
    'namespace',
    'xml_error_type',
    'xml_line',
    'xml_column',
    'xml_path',
    'position',
    'expected_positions',
    'missing_count',
    'missing',
    'interval_start',
    'interval_end',
    'resolution',
    'resolution_unit',
    'volume',
    'volume_limit',
    'condition',
    'size_bytes',
    'limit_bytes',
    'position_timestamp',
    'direction',
    'incoming_document_id',
    'stored_document_id',
    'incoming_delivery_id',
    'stored_delivery_id',
    'product',
    'unit',
    'feature',
    'import_log_id',
    'reason',
    'stale',
    'duplicate',
    'original_existing',
] as const

export type SdatIssueParamKey = typeof SDAT_ISSUE_PARAM_ORDER[number]

/** Renderable (key, value) pairs of an issue's structured params. Arrays
 * (e.g. `missing` positions) are shortened; original prose stays in the API. */
export function sdatIssueParams(issue: SdatIssue): Array<{ key: SdatIssueParamKey; value: string }> {
    const params: Array<{ key: SdatIssueParamKey; value: string }> = []
    for (const key of SDAT_ISSUE_PARAM_ORDER) {
        const raw = issue[key]
        if (raw === null || raw === undefined || raw === '') continue
        if (Array.isArray(raw)) {
            if (raw.length === 0) continue
            const shown = raw.slice(0, 10).map((entry) => String(entry)).join(', ')
            params.push({ key, value: raw.length > 10 ? `${shown} (+${raw.length - 10})` : shown })
        } else if (typeof raw === 'string' || typeof raw === 'number' || typeof raw === 'boolean') {
            params.push({ key, value: String(raw) })
        }
    }
    return params
}
