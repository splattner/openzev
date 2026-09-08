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
export type AssignmentState = 'current' | 'upcoming' | 'ended'

export function getAssignmentState(assignment: MeteringPointAssignment, todayIso: string): AssignmentState {
  if (assignment.valid_from > todayIso) return 'upcoming'
  if (assignment.valid_to && assignment.valid_to < todayIso) return 'ended'
  return 'current'
}

/** Whether `assignment` is in force today — i.e. its meter currently has a holder. */
export function isAssignmentCurrent(assignment: MeteringPointAssignment, todayIso: string): boolean {
  return getAssignmentState(assignment, todayIso) === 'current'
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

function addDaysIso(iso: string, days: number): string {
  const [year, month, day] = iso.split('-').map(Number)
  const date = new Date(year, month - 1, day + days)
  const yyyy = date.getFullYear()
  const mm = String(date.getMonth() + 1).padStart(2, '0')
  const dd = String(date.getDate()).padStart(2, '0')
  return `${yyyy}-${mm}-${dd}`
}

export type NextAssignmentGuidance = {
  /** Suggested `valid_from` for a new assignment: the day after the latest existing `valid_to`, or today if there is no assignment history. */
  suggestedValidFrom: string
  /** Whether an existing assignment on this meter is open-ended (no `valid_to`) and would overlap a new one. */
  hasOpenEndedAssignment: boolean
}

/**
 * Guidance for creating the *next* assignment on a meter that may already
 * have assignment history (e.g. a tenant handover). Mirrors the backend's
 * non-overlap rule (`MeteringPointAssignment._validate_no_overlap`): an
 * open-ended assignment blocks any later one, so it must be closed first.
 */
export function getNextAssignmentGuidance(assignments: MeteringPointAssignment[], todayIso: string): NextAssignmentGuidance {
  const hasOpenEndedAssignment = assignments.some((assignment) => !assignment.valid_to)
  const latestValidTo = assignments
    .map((assignment) => assignment.valid_to)
    .filter((value): value is string => !!value)
    .sort()
    .at(-1)

  return {
    suggestedValidFrom: latestValidTo ? addDaysIso(latestValidTo, 1) : todayIso,
    hasOpenEndedAssignment,
  }
}
