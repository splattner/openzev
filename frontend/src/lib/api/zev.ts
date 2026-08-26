import type {
  MeteringPoint,
  MeteringPointAssignment,
  MeteringPointAssignmentInput,
  MeteringPointInput,
  Participant,
  ParticipantAccountCreateResult,
  ParticipantInput,
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

export async function createZev(payload: ZevInput): Promise<Zev> {
  const { data } = await api.post<Zev>('/zev/zevs/', payload)
  return data
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

export async function sendParticipantInvitation(id: string): Promise<{ detail: string; username: string; temporary_password: string }> {
  const { data } = await api.post<{ detail: string; username: string; temporary_password: string }>(`/zev/participants/${id}/send-invitation/`)
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

export async function createParticipantAccount(participantId: string, payload: { username?: string; email?: string }): Promise<ParticipantAccountCreateResult> {
  const { data } = await api.post<ParticipantAccountCreateResult>(`/zev/participants/${participantId}/create-account/`, payload)
  return data
}

export async function downloadParticipantContractPdf(participantId: string, filename: string): Promise<void> {
  const response = await api.get(`/zev/participants/${participantId}/contract-pdf/`, { responseType: 'blob' })
  downloadBlob(response.data as Blob, filename)
}

export async function fetchMeteringPoints(): Promise<MeteringPoint[]> {
  return fetchAllPages<MeteringPoint>('/zev/metering-points/')
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
