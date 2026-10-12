import { todayBusinessIso } from '../../lib/dates'
import type {
  Building,
  MeteringPoint,
  MeteringPointAssignment,
  MeteringPointAssignmentInput,
  MeteringPointDataQuality,
  MeteringPointInput,
} from '../../types/api'

export const defaultMeteringPointForm = (): MeteringPointInput => ({
  zev: '',
  meter_id: '',
  meter_type: 'consumption',
  is_active: true,
  location_description: '',
  has_behind_meter_generation: false,
})

export const defaultAssignmentForm = (meteringPointId = ''): MeteringPointAssignmentInput => ({
  metering_point: meteringPointId,
  participant: '',
  valid_from: todayBusinessIso(),
  valid_to: null,
  allocation_mode: 'personal',
})

export type MeteringPointTypeFilter = 'all' | MeteringPoint['meter_type']
/** `'all'`, or the id of one building (#890). */
export type MeteringPointBuildingFilter = string
export type BuildingGroup = { building: Building; points: MeteringPoint[] }

/**
 * Groups already-filtered metering points by building, ordered by building
 * name. A group with no matching card is hidden, except a building that has no
 * metering points at all, which stays visible while no filter is active.
 */
export function groupMeteringPointsByBuilding(
  buildings: Building[],
  points: MeteringPoint[],
  { filtersActive }: { filtersActive: boolean },
): BuildingGroup[] {
  return [...buildings]
    .sort((left, right) => left.name.localeCompare(right.name) || left.id.localeCompare(right.id))
    .map((building) => ({ building, points: points.filter((point) => point.building === building.id) }))
    .filter((group) => group.points.length > 0 || (!filtersActive && group.building.metering_point_count === 0))
}

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

// ── Data health (#623) ──────────────────────────────────────────────────────

const HEALTH_WINDOW_DAYS = 30

/** The rolling window the health check inspects: the last `days` complete days, ending yesterday. Today's readings arrive with the next import, so a window ending today would read every meter as having a one-day gap. */
export function getMeteringPointHealthWindow(todayIso: string, days = HEALTH_WINDOW_DAYS): { from: string; to: string } {
  return { from: addDaysIso(todayIso, -days), to: addDaysIso(todayIso, -1) }
}

export type MeteringPointHealth = 'green' | 'yellow' | 'red' | 'no_data'

/**
 * A meter's data-health state: `no_data` when it has never received a
 * reading (distinct from a completeness of 0% within the window, which is
 * `red` — a meter whose imports stopped is a different problem than one
 * that never started), otherwise the data-quality-status severity for the
 * inspection window.
 */
export function getMeteringPointHealth(
  point: Pick<MeteringPoint, 'reading_count'>,
  quality: MeteringPointDataQuality | undefined,
): MeteringPointHealth {
  if (!point.reading_count) return 'no_data'
  return quality?.severity ?? 'no_data'
}

/**
 * A meter with recorded readings but no assignment valid *today* — its
 * energy is being metered but cannot be attributed (and therefore not
 * billed) to anyone. Mirrors the Participants page's "no metering point"
 * warning from the other direction.
 *
 * `false` for an inactive meter (out of billing scope) or one with no
 * readings yet (nothing to attribute) — those are surfaced via
 * `getMeteringPointHealth` instead, not this warning.
 */
export function isMeteringPointHolderLess(
  point: Pick<MeteringPoint, 'is_active' | 'reading_count'>,
  assignments: MeteringPointAssignment[],
  todayIso: string,
): boolean {
  if (!point.is_active || !point.reading_count) return false
  return !assignments.some((assignment) => isAssignmentCurrent(assignment, todayIso))
}

/** Whether a meter should be surfaced by the "needs attention" filter before a billing run. Always `false` for an inactive meter — it is out of billing scope. */
export function meteringPointNeedsAttention(
  point: Pick<MeteringPoint, 'is_active'>,
  health: MeteringPointHealth,
  holderLess: boolean,
): boolean {
  return point.is_active && (health !== 'green' || holderLess)
}


export function meteringPointHealthBadgeClass(health: MeteringPointHealth): string {
  if (health === 'green') return 'badge badge-success'
  if (health === 'yellow') return 'badge badge-warning'
  if (health === 'red') return 'badge badge-danger'
  return 'badge badge-neutral'
}

/**
 * One glance at a meter: the data health, with a missing holder counted as the
 * worst case and an inactive meter set apart (it is out of billing scope, so
 * its health is not a problem to act on).
 */
export type MeteringPointStatus = 'ok' | 'warning' | 'danger' | 'pending' | 'inactive'

export function getMeteringPointStatus(
  point: Pick<MeteringPoint, 'is_active'>,
  health: MeteringPointHealth,
  holderLess: boolean,
): MeteringPointStatus {
  if (!point.is_active) return 'inactive'
  if (holderLess || health === 'red') return 'danger'
  if (health === 'yellow') return 'warning'
  if (health === 'no_data') return 'pending'
  return 'ok'
}

/** The status's key under `pages.meteringPoints.health`, for its label. */
export function meteringPointStatusLabelKey(
  status: MeteringPointStatus,
  health: MeteringPointHealth,
  holderLess: boolean,
): string {
  if (status === 'inactive') return 'pages.meteringPoints.inactive'
  if (holderLess) return 'pages.meteringPoints.holderLessBadge'
  return `pages.meteringPoints.health.${health}`
}

/** How many of `points` are in each status. */
export function countMeteringPointStatuses(
  points: MeteringPoint[],
  statusById: Map<string, MeteringPointStatus>,
): Record<MeteringPointStatus, number> {
  const counts: Record<MeteringPointStatus, number> = { ok: 0, warning: 0, danger: 0, pending: 0, inactive: 0 }
  for (const point of points) counts[statusById.get(point.id) ?? 'pending'] += 1
  return counts
}

// ── Sort ────────────────────────────────────────────────────────────────────

/** `attention`: the meters to act on first; the rest order by the field they name. */
export type MeteringPointSort = 'attention' | 'meter_id' | 'location' | 'last_reading'

const STATUS_RANK: Record<MeteringPointStatus, number> = { danger: 0, warning: 1, pending: 2, ok: 3, inactive: 4 }

export function readMeteringPointSort(value: string | null): MeteringPointSort {
  return value === 'meter_id' || value === 'location' || value === 'last_reading' ? value : 'attention'
}

/** A new array: `last_reading` puts the stalest first (a meter that never reported leads), because that is the one to look at. */
export function sortMeteringPoints(
  points: MeteringPoint[],
  sort: MeteringPointSort,
  statusById: Map<string, MeteringPointStatus>,
): MeteringPoint[] {
  const byMeterId = (left: MeteringPoint, right: MeteringPoint) =>
    left.meter_id.localeCompare(right.meter_id, undefined, { numeric: true })
  const compare = (left: MeteringPoint, right: MeteringPoint): number => {
    if (sort === 'attention') {
      const delta = STATUS_RANK[statusById.get(left.id) ?? 'pending'] - STATUS_RANK[statusById.get(right.id) ?? 'pending']
      return delta || byMeterId(left, right)
    }
    if (sort === 'location') {
      const leftLocation = left.location_description?.trim() ?? ''
      const rightLocation = right.location_description?.trim() ?? ''
      // An unset location sorts last, not first.
      if (!leftLocation !== !rightLocation) return leftLocation ? -1 : 1
      return leftLocation.localeCompare(rightLocation, undefined, { numeric: true }) || byMeterId(left, right)
    }
    if (sort === 'last_reading') {
      const leftAt = left.last_reading_at ?? ''
      const rightAt = right.last_reading_at ?? ''
      return leftAt.localeCompare(rightAt) || byMeterId(left, right)
    }
    return byMeterId(left, right)
  }
  return [...points].sort(compare)
}

// ── Filters as URL state (#625) ─────────────────────────────────────────────
//
// Each `read*` function turns a raw `?param=` value (or a hand-edited/stale
// one that no longer matches the type) into a valid filter value, falling
// back to the unfiltered default rather than throwing — a URL is never
// trusted input. Pairs with the query-param names in `META_POINT_FILTER_KEYS`.

export const METERING_POINT_FILTER_KEYS = {
  search: 'search',
  view: 'view',
  type: 'type',
  building: 'building',
} as const

/** Not one of the filters: "Clear filters" leaves the sort as it is. */
export const METERING_POINT_SORT_KEY = 'sort'

export function readMeteringPointBuildingFilter(value: string | null): MeteringPointBuildingFilter {
  return value || 'all'
}

export function readMeteringPointTypeFilter(value: string | null): MeteringPointTypeFilter {
  return value === 'consumption' || value === 'production' || value === 'bidirectional' ? value : 'all'
}

/**
 * The list's one counted view (`FilterTabs`): a status, the meters without a
 * holder today (as `getMeteringPointCounts`' `assignedCount` counts them), or
 * those needing attention.
 */
export type MeteringPointView = 'all' | 'active' | 'inactive' | 'unassigned' | 'attention'

export function readMeteringPointView(value: string | null): MeteringPointView {
  return value === 'active' || value === 'inactive' || value === 'unassigned' || value === 'attention' ? value : 'all'
}
