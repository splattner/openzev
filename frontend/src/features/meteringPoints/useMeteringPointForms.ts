import { todayLocalIso } from '../../lib/dates'
import type { MeteringPoint, MeteringPointAssignment, MeteringPointAssignmentInput, MeteringPointInput } from '../../types/api'

export const defaultMeteringPointForm = (): MeteringPointInput => ({
  zev: '',
  meter_id: '',
  meter_type: 'consumption',
  is_active: true,
  location_description: '',
})

export const defaultAssignmentForm = (meteringPointId = ''): MeteringPointAssignmentInput => ({
  metering_point: meteringPointId,
  participant: '',
  valid_from: todayLocalIso(),
  valid_to: null,
  allocation_mode: 'personal',
})

export type MeteringPointStatusFilter = 'all' | 'active' | 'inactive'
export type MeteringPointTypeFilter = 'all' | MeteringPoint['meter_type']
type AssignmentState = 'current' | 'upcoming' | 'ended'

export function getAssignmentState(assignment: MeteringPointAssignment, todayIso: string): AssignmentState {
  if (assignment.valid_from > todayIso) return 'upcoming'
  if (assignment.valid_to && assignment.valid_to < todayIso) return 'ended'
  return 'current'
}

export function assignmentStateBadgeClass(state: AssignmentState): string {
  if (state === 'current') return 'badge badge-success'
  if (state === 'upcoming') return 'badge badge-info'
  return 'badge badge-neutral'
}

export function assignmentStateSortOrder(state: AssignmentState): number {
  if (state === 'current') return 0
  if (state === 'upcoming') return 1
  return 2
}
