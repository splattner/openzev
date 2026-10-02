import type {
  GridOperatorList,
  Party,
  PartyInput,
  PartyRoleName,
  ZevPartyRole,
  ZevAccessGrant,
  ZevAccessGrantCreated,
  ZevAccessGrantInput,
  ZevAccessRole,
  GridOperatorSuggestion,
  MeteringPoint,
  MeteringPointAssignment,
  MeteringPointAssignmentInput,
  MeteringPointInput,
  Participant,
  ParticipantInput,
  ParticipantOnboardingLinkResult,
  SelfSetupZevInput,
  SendOnboardingLinkResult,
  Zev,
  ZevInput,
  ZevWizardInput,
  ZevWizardResult,
} from '../../types/api'
import { api } from './client'
import { downloadBlob } from '../downloadBlob'
import { fetchAllPages } from './pagination'

export async function createSelfSetupZev(
  payload: SelfSetupZevInput,
): Promise<{ zev: { id: string; name: string }; owner_participant_id: string }> {
  const { data } = await api.post('/zev/zevs/self-setup/', payload)
  return data
}

export async function fetchZevs(): Promise<Zev[]> {
  return fetchAllPages<Zev>('/zev/zevs/')
}

export async function createZevWithOwner(payload: ZevWizardInput): Promise<ZevWizardResult> {
  const { data } = await api.post<ZevWizardResult>('/zev/zevs/create-with-owner/', payload)
  return data
}

export async function updateZev(id: string, payload: Partial<ZevInput>): Promise<Zev> {
  const { data } = await api.patch<Zev>(`/zev/zevs/${id}/`, payload)
  return data
}

/** Disable a ZEV — reversible, touches nothing under it. The ZEV's own owner or an admin may call this. */
export async function disableZev(id: string, reason?: string): Promise<Zev> {
  const { data } = await api.post<Zev>(`/zev/zevs/${id}/disable/`, { reason: reason ?? '' })
  return data
}

/** Re-enable a disabled ZEV. Admin only — its owner cannot self-serve this. */
export async function enableZev(id: string): Promise<Zev> {
  const { data } = await api.post<Zev>(`/zev/zevs/${id}/enable/`)
  return data
}

export interface ZevPurgeResult {
  detail: string
  deleted_counts: Record<string, number>
  media_files_deleted: number
}

/**
 * Permanently delete a disabled ZEV and everything under it. Admin only,
 * irreversible. `confirmName` must match the ZEV's exact name, the same
 * friction the backend requires.
 */
export async function purgeZev(id: string, confirmName: string): Promise<ZevPurgeResult> {
  const { data } = await api.post<ZevPurgeResult>(`/zev/zevs/${id}/purge/`, { confirm_name: confirmName })
  return data
}

export async function fetchParticipants(): Promise<Participant[]> {
  return fetchAllPages<Participant>('/zev/participants/')
}

export async function createParticipant(payload: ParticipantInput): Promise<Participant> {
  const { data } = await api.post<Participant>('/zev/participants/', payload)
  return data
}

export async function updateParticipant(id: string, payload: Partial<ParticipantInput>): Promise<Participant> {
  const { data } = await api.patch<Participant>(`/zev/participants/${id}/`, payload)
  return data
}

export async function deleteParticipant(id: string): Promise<void> {
  await api.delete(`/zev/participants/${id}/`)
}

/** Email the onboarding link to the address on the participant's record. */
export async function sendOnboardingLink(id: string): Promise<SendOnboardingLinkResult> {
  const { data } = await api.post<SendOnboardingLinkResult>(`/zev/participants/${id}/send-onboarding-link/`)
  return data
}

/**
 * Ensure an account and onboarding link exist, without emailing it.
 *
 * Backs "copy onboarding link" — no address required, since nothing is sent —
 * and also the admin console's account-linking action, which never required
 * one either.
 */
export async function getOnboardingLink(id: string): Promise<ParticipantOnboardingLinkResult> {
  const { data } = await api.post<ParticipantOnboardingLinkResult>(`/zev/participants/${id}/onboarding-link/`)
  return data
}

export async function revokeOnboardingLink(id: string): Promise<Participant> {
  const { data } = await api.post<Participant>(`/zev/participants/${id}/revoke-onboarding-link/`)
  return data
}

export async function linkParticipantAccount(participantId: string, userId: number): Promise<Participant> {
  const { data } = await api.post<Participant>(`/zev/participants/${participantId}/link-account/`, { user_id: userId })
  return data
}

export async function unlinkParticipantAccount(participantId: string): Promise<Participant> {
  const { data } = await api.post<Participant>(`/zev/participants/${participantId}/unlink-account/`)
  return data
}


// POST, not GET: this issues the contract (mints a document number, writes a
// ContractIssue and an audit event). The backend keeps GET as a pure read of
// an already-issued snapshot, so the write stays under CSRF protection.
export async function downloadParticipantContractPdf(participantId: string, filename: string): Promise<void> {
  const response = await api.post(`/zev/participants/${participantId}/contract-pdf/`, null, { responseType: 'blob' })
  downloadBlob(response.data as Blob, filename)
}

/** The latest already-issued contract, without issuing a new version — what a
 * viewer may download (#761). The backend answers 404 before the first issue. */
export async function downloadIssuedParticipantContractPdf(participantId: string, filename: string): Promise<void> {
  const response = await api.get(`/zev/participants/${participantId}/contract-pdf/`, { responseType: 'blob' })
  downloadBlob(response.data as Blob, filename)
}

/**
 * Whether `FeatureFlag.PARTICIPANT_GEOCODING_ENABLED` is on — checked by any
 * authenticated role, mirroring `fetchFeasibilityCalculatorEnabled`. Off by
 * default; the participant map section is not rendered at all when this is
 * false, rather than rendered empty, since a previously cached building
 * footprint can still exist from before the flag was turned off (see #796).
 */
export async function fetchParticipantGeocodingEnabled(): Promise<boolean> {
  const { data } = await api.get<{ enabled: boolean }>('/zev/participants/geocoding-enabled/')
  return data.enabled
}

export async function fetchGridOperators(): Promise<GridOperatorList> {
  const { data } = await api.get<GridOperatorList>('/zev/grid-operators/')
  return data
}

/**
 * Operator suggestion(s) for a postal code — zero, one, or a short list.
 * Looked up server-side against the same checked-in fixture as
 * `fetchGridOperators`, so an unrecognised or foreign postal code simply
 * resolves to `{ operators: [] }` rather than an error.
 */
export async function fetchGridOperatorSuggestions(postalCode: string): Promise<GridOperatorSuggestion> {
  const { data } = await api.get<GridOperatorSuggestion>('/zev/grid-operators/suggest/', {
    params: { postal_code: postalCode },
  })
  return data
}

export async function fetchMeteringPoints(zevId?: string): Promise<MeteringPoint[]> {
  const params = zevId ? { zev_id: zevId } : {}
  return fetchAllPages<MeteringPoint>('/zev/metering-points/', params)
}

export async function createMeteringPoint(payload: MeteringPointInput): Promise<MeteringPoint> {
  const { data } = await api.post<MeteringPoint>('/zev/metering-points/', payload)
  return data
}

export async function updateMeteringPoint(id: string, payload: Partial<MeteringPointInput>): Promise<MeteringPoint> {
  const { data } = await api.patch<MeteringPoint>(`/zev/metering-points/${id}/`, payload)
  return data
}

export async function deleteMeteringPoint(id: string): Promise<void> {
  await api.delete(`/zev/metering-points/${id}/`)
}

export async function deleteMeteringPointReadings(
  id: string,
  payload: { delete_all: boolean; date_from?: string; date_to?: string },
): Promise<{ deleted_count: number }> {
  const { data } = await api.post<{ deleted_count: number }>(`/zev/metering-points/${id}/delete-readings/`, payload)
  return data
}

export async function fetchMeteringPointAssignments(meteringPointId?: string): Promise<MeteringPointAssignment[]> {
  const params = meteringPointId ? { metering_point: meteringPointId } : {}
  return fetchAllPages<MeteringPointAssignment>('/zev/metering-point-assignments/', params)
}

export async function createMeteringPointAssignment(payload: MeteringPointAssignmentInput): Promise<MeteringPointAssignment> {
  const { data } = await api.post<MeteringPointAssignment>('/zev/metering-point-assignments/', payload)
  return data
}

export async function updateMeteringPointAssignment(id: string, payload: Partial<MeteringPointAssignmentInput>): Promise<MeteringPointAssignment> {
  const { data } = await api.patch<MeteringPointAssignment>(`/zev/metering-point-assignments/${id}/`, payload)
  return data
}

export async function deleteMeteringPointAssignment(id: string): Promise<void> {
  await api.delete(`/zev/metering-point-assignments/${id}/`)
}

// ── Access to a ZEV (#761) ────────────────────────────────────────────────

export async function fetchZevAccess(zevId: string, { includeEnded = false } = {}): Promise<ZevAccessGrant[]> {
  const { data } = await api.get<ZevAccessGrant[]>(`/zev/zevs/${zevId}/access/`, {
    params: includeEnded ? { include_ended: 'true' } : undefined,
  })
  return data
}

export async function createZevAccess(zevId: string, input: ZevAccessGrantInput): Promise<ZevAccessGrantCreated> {
  const { data } = await api.post<ZevAccessGrantCreated>(`/zev/zevs/${zevId}/access/`, input)
  return data
}

export async function updateZevAccess(
  zevId: string,
  grantId: string,
  input: { role?: ZevAccessRole; valid_to?: string | null },
): Promise<ZevAccessGrant> {
  const { data } = await api.patch<ZevAccessGrant>(`/zev/zevs/${zevId}/access/${grantId}/`, input)
  return data
}

export async function revokeZevAccess(zevId: string, grantId: string): Promise<void> {
  await api.delete(`/zev/zevs/${zevId}/access/${grantId}/`)
}

export async function resendZevInvitation(zevId: string, grantId: string): Promise<{ email_sent: boolean }> {
  const { data } = await api.post<{ email_sent: boolean }>(`/zev/zevs/${zevId}/access/${grantId}/resend-invitation/`)
  return data
}

// ── Parties and their dated roles (#761, SPEC-2026-10-zev-parties §5.2–5.3) ──

export async function fetchParties(zevId: string): Promise<Party[]> {
  return fetchAllPages<Party>('/zev/parties/', { zev_id: zevId })
}

export async function createParty(input: PartyInput & { zev: string }): Promise<Party> {
  const { data } = await api.post<Party>('/zev/parties/', input)
  return data
}

export async function updateParty(id: string, input: Partial<PartyInput>): Promise<Party> {
  const { data } = await api.patch<Party>(`/zev/parties/${id}/`, input)
  return data
}

export async function deleteParty(id: string): Promise<void> {
  await api.delete(`/zev/parties/${id}/`)
}

export async function fetchPartyRoles(zevId: string, { includeEnded = false } = {}): Promise<ZevPartyRole[]> {
  return fetchAllPages<ZevPartyRole>('/zev/party-roles/', {
    zev_id: zevId,
    ...(includeEnded ? { include_ended: 'true' } : {}),
  })
}

export async function assignPartyRole(input: {
  zev: string
  party: string
  role: PartyRoleName
  valid_from: string
  valid_to?: string | null
}): Promise<ZevPartyRole> {
  const { data } = await api.post<ZevPartyRole>('/zev/party-roles/', input)
  return data
}

/** Ends the role on ``lastDay``; ``null`` when that removed a role that had not started yet. */
export async function endPartyRole(id: string, lastDay: string): Promise<ZevPartyRole | null> {
  const response = await api.post<ZevPartyRole>(`/zev/party-roles/${id}/end/`, { last_day: lastDay })
  return response.status === 204 ? null : response.data
}
