import type { ApiKeyStatus } from '../features/account/apiKeyStatus'
import type { VerificationState } from '../features/backups/backupHelpers'
import type { DocumentStanding } from '../features/inbox/documentPresentation'
import type { AssignmentState } from '../features/meteringPoints/useMeteringPointForms'
import type { ParticipantValidityState } from '../features/participants/types'
import type {
  AccessCredential,
  AuditEventStatus,
  BackupJobStatus,
  CreditStatus,
  DataQualitySeverity,
  DynamicTariffSource,
  EmailLog,
  SupplementaryStatus,
  VseTariffCandidateStatus,
} from '../types/api'

export type BadgeTone = 'neutral' | 'info' | 'success' | 'warning' | 'danger' | 'brand' | 'tag'

export interface StatusTreatment {
  tone: BadgeTone
  /** Outlined instead of tinted; only warning and danger have a quiet form. */
  quiet?: boolean
}

type Treatments<S extends string> = Record<S, StatusTreatment>

/**
 * Treatments are workflow-specific: `sent` is a neutral invoice step but a
 * successful email outcome. Each map names every state of its union, so a new
 * state fails to compile until it has a treatment.
 */
const STATUS_TONES = {
  // `Invoice['status']` is an untyped string; unknown values render neutral.
  invoice: {
    draft: { tone: 'tag' },
    approved: { tone: 'tag' },
    sent: { tone: 'tag' },
    paid: { tone: 'success' },
    cancelled: { tone: 'danger' },
  },
  credit: {
    open: { tone: 'info' },
    used: { tone: 'neutral' },
    refunded: { tone: 'success' },
  } satisfies Treatments<CreditStatus>,
  email: {
    pending: { tone: 'info' },
    sent: { tone: 'success' },
    failed: { tone: 'danger', quiet: true },
  } satisfies Treatments<EmailLog['status']>,
  // Backup and restore jobs share one status set.
  backup: {
    queued: { tone: 'neutral' },
    running: { tone: 'info' },
    completed: { tone: 'success' },
    failed: { tone: 'danger', quiet: true },
  } satisfies Treatments<BackupJobStatus>,
  verification: {
    checking: { tone: 'info' },
    never: { tone: 'neutral' },
    ok: { tone: 'success' },
    failed: { tone: 'danger', quiet: true },
  } satisfies Treatments<VerificationState>,
  audit: {
    started: { tone: 'neutral' },
    queued: { tone: 'info' },
    success: { tone: 'success' },
    failed: { tone: 'danger' },
    denied: { tone: 'danger' },
  } satisfies Treatments<AuditEventStatus>,
  tariffImport: {
    new: { tone: 'success' },
    new_version: { tone: 'info' },
    duplicate: { tone: 'neutral' },
    conflict: { tone: 'warning', quiet: true },
    unsupported: { tone: 'danger', quiet: true },
  } satisfies Treatments<VseTariffCandidateStatus>,
  assignment: {
    current: { tone: 'success' },
    upcoming: { tone: 'info' },
    ended: { tone: 'neutral' },
  } satisfies Treatments<AssignmentState>,
  participantValidity: {
    current: { tone: 'neutral' },
    upcoming: { tone: 'info' },
    ended: { tone: 'neutral' },
  } satisfies Treatments<ParticipantValidityState>,
  documentStanding: {
    withdrawn: { tone: 'warning', quiet: true },
    cancelled: { tone: 'warning', quiet: true },
    superseded: { tone: 'neutral' },
  } satisfies Treatments<NonNullable<DocumentStanding>>,
  credential: {
    active: { tone: 'success' },
    revoked: { tone: 'danger', quiet: true },
    expired: { tone: 'warning', quiet: true },
    expiring: { tone: 'warning', quiet: true },
  } satisfies Treatments<AccessCredential['status'] | ApiKeyStatus>,
  supplementary: {
    ok: { tone: 'success' },
    pending: { tone: 'neutral' },
    error: { tone: 'warning', quiet: true },
    reconnect_required: { tone: 'danger', quiet: true },
    disabled: { tone: 'neutral' },
  } satisfies Treatments<SupplementaryStatus>,
  // `disabled` is the source switched off, shown in place of its last fetch.
  priceSource: {
    ok: { tone: 'success' },
    failed: { tone: 'danger' },
    pending: { tone: 'neutral' },
    disabled: { tone: 'neutral' },
  } satisfies Treatments<DynamicTariffSource['last_fetch_status'] | 'disabled'>,
  dataQuality: {
    green: { tone: 'success' },
    yellow: { tone: 'warning', quiet: true },
    red: { tone: 'danger' },
  } satisfies Treatments<DataQualitySeverity>,
} satisfies Record<string, Record<string, StatusTreatment>>

export type StatusDomain = keyof typeof STATUS_TONES

const NEUTRAL: StatusTreatment = { tone: 'neutral' }

/** The treatment for a status; an unknown API value renders neutral. */
export function statusTreatment(status: string | null | undefined, domain: StatusDomain): StatusTreatment {
  const tones: Record<string, StatusTreatment> = STATUS_TONES[domain]
  return status && Object.hasOwn(tones, status) ? tones[status] : NEUTRAL
}
