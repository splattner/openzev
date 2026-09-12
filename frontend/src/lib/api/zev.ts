import type {
  GridOperatorList,
  GridOperatorSuggestion,
  MeteringPoint,
  MeteringPointAssignment,
  MeteringPointAssignmentInput,
  MeteringPointInput,
  Participant,
  ParticipantInput,
  ParticipantOnboardingLinkResult,
  SelfSetupZevInput,
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

export async function deleteZev(id: string): Promise<void> {
  await api.delete(`/zev/zevs/${id}/`)
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
export async function sendOnboardingLink(id: string): Promise<{ detail: string; onboarding_url: string }> {
  const { data } = await api.post<{ detail: string; onboarding_url: string }>(`/zev/participants/${id}/send-onboarding-link/`)
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
